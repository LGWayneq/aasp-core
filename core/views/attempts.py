from datetime import timedelta, datetime

import re
import base64
import cv2
import requests
import os
import numpy as np
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from insightface.app import FaceAnalysis
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, renderer_classes
from rest_framework.renderers import JSONRenderer

from core.decorators import groups_allowed, UserGroup
from core.models import Assessment, AssessmentAttempt, \
    CodeQuestionAttempt, CodeQuestion, TestCase, CodeSnippet, CodeQuestionAttemptSnippet, CodeQuestionSubmission, TestCaseAttempt, Language, \
    McqQuestion, McqQuestionOption, McqQuestionAttempt, McqQuestionAttemptOption, \
    CandidateSnapshot
from core.tasks import update_test_case_attempt_status, force_submit_assessment, detect_faces
from core.views.utils import get_assessment_attempt_question, check_permissions_course, user_enrolled_in_course, construct_expected_output_judge0_params, construct_judge0_params, decode_judge0_params
from core.concurrency import evaluate_concurrency_results, get_max_threads_used

@login_required()
@groups_allowed(UserGroup.educator, UserGroup.lab_assistant, UserGroup.student)
def assessment_landing(request, assessment_id):
    """
    Landing page of an Assessment
    - Displays the various information about an assessment
    - Candidates can start the assessment from here (only when published)
    - Educators can preview assessments from here (only when unpublished)
    """

    # get assessment object
    assessment = get_object_or_404(Assessment, id=assessment_id)

    # if assessment is not published, it should only be accessible to educators for preview
    if not assessment.published:
        # must be course owner or maintainer
        if check_permissions_course(assessment.course, request.user) == 0:
            raise PermissionDenied()

        # check if assessment is valid for previewing
        valid, msg = assessment.is_valid()
        if not valid:
            messages.warning(request, f"Assessment is incomplete! {msg}")
            return redirect("assessment-details", assessment_id=assessment_id)

    # if assessment is published, it should only be accessible to candidates
    else:
        # check if user is enrolled in the course (students)
        if not user_enrolled_in_course(assessment.course, request.user):
            raise PermissionDenied("You are not enrolled in this course.")

    # check for incomplete attempts
    incomplete_attempt: bool = AssessmentAttempt.objects.filter(assessment=assessment, candidate=request.user,
                                                                time_submitted=None).exists()

    # get current number of attempts by the user
    attempt_count: int = AssessmentAttempt.objects.filter(assessment=assessment, candidate=request.user).count()

    # check if there are any attempts remaining
    no_more_attempts: bool = False if assessment.num_attempts == 0 else attempt_count >= assessment.num_attempts

    # get all existing assessment attempts
    assessment_attempts = AssessmentAttempt.objects.filter(assessment=assessment, candidate=request.user)

    # context
    context = {
        'assessment': assessment,
        'assessment_attempts': assessment_attempts,
        'attempt_count': attempt_count,
        'incomplete_attempt': incomplete_attempt,
        'no_more_attempts': no_more_attempts,
    }

    return render(request, 'attempts/assessment-landing.html', context)


@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def enter_assessment(request, assessment_id):
    """
    This view will redirect the user to the assessment.

    If an incomplete AssessmentAttempt exists:
     - redirect to first question of this attempt

    If an AssessmentAttempt does not exist:
     - use generateAttempt() to generate records
     - redirect to first question of this attempt
    """

    # POST method is used to prevent CSRF attacks
    if request.method == "POST":

        # get assessment object
        assessment = get_object_or_404(Assessment, id=assessment_id)
        pin = request.POST.get('pin')
        candidate = request.user

        # get incomplete attempt
        incomplete_attempt = AssessmentAttempt.objects.filter(assessment=assessment, candidate=candidate,
                                                              time_submitted=None).first()

        # if assessment is not published, it should only be accessible to educators for preview
        if not assessment.published:
            if check_permissions_course(assessment.course, candidate) == 0:
                raise PermissionDenied()

        # if assessment is published, it should only be accessible to candidates
        else:
            # check if user is enrolled in the course (students)
            if not user_enrolled_in_course(assessment.course, candidate):
                raise PermissionDenied("You are not enrolled in this course.")

            # check if assessment is active, don't deny if there is an existing incomplete attempt
            if assessment.status != "Active" and not incomplete_attempt:
                messages.warning(request, "You may not enter this assessment.")
                return redirect('assessment-landing', assessment_id=assessment.id)

        # if incomplete attempt exists, redirect to it
        if incomplete_attempt:
            return redirect('attempt-question', assessment_attempt_id=incomplete_attempt.id, question_index=0)

        # create a new attempt if there are attempts left
        attempt_count = AssessmentAttempt.objects.filter(assessment=assessment, candidate=candidate).count()
        if assessment.num_attempts != 0 and attempt_count >= assessment.num_attempts:  # all attempts used up
            messages.warning(request, "You may not enter this assessment.")
            return redirect('assessment-landing', assessment_id=assessment.id)
        else:
            # check pin, if needed
            if assessment.pin is not None and str(assessment.pin) != pin:
                messages.warning(request, "Incorrect PIN supplied, unable to start a new attempt.")
                return redirect('assessment-landing', assessment_id=assessment.id)

            # generate new assessment_attempt
            assessment_attempt = generate_assessment_attempt(candidate, assessment)
            
            # upload initial candidate snapshot
            if assessment.require_webcam:
                attempt_number = request.POST.get('attempt_number')
                timestamp = request.POST.get('timestamp')
                timestamp_tz = timezone.make_aware(datetime.strptime(timestamp, "%d-%m-%Y %H:%M:%S"))
                image = request.FILES['image']

                snapshot = CandidateSnapshot(assessment_attempt=assessment_attempt, 
                                            attempt_number=attempt_number, timestamp=timestamp_tz, image=image)
                snapshot.save()

                """ 
                if celery worker container is running on a machine that's different from dev machine, use local_detect_faces instead of detect_faces.delay.
                cannot queue as task because MEDIA_ROOT are different directories
                """
                # if settings.DEBUG:
                #     local_detect_faces(snapshot)

                detect_faces.delay(snapshot.id)

            return redirect('attempt-question', assessment_attempt_id=assessment_attempt.id, question_index=0)

    raise Http404()


def generate_assessment_attempt(user, assessment):
    """
    Generates a AssessmentAttempt instance for a user and assessment then,
    generates a cq_attempt instance for each CodeQuestion added to this assessment.
    (If there are other types of questions in the future, they should be generated here as well)
    """
    with transaction.atomic():
        # create assessment attempt object
        assessment_attempt = AssessmentAttempt.objects.create(candidate=user, assessment=assessment)

        # generate a mcq_attempt for each mcq question in the assessment
        mcq_questions = McqQuestion.objects.filter(assessment=assessment).order_by('id')
        mcq_attempts = [McqQuestionAttempt(assessment_attempt=assessment_attempt, mcq_question=mcq) for mcq in mcq_questions]
        McqQuestionAttempt.objects.bulk_create(mcq_attempts)

        # generate a cq_attempt for each code question in the assessment
        code_questions = CodeQuestion.objects.filter(assessment=assessment).order_by('id')
        cq_attempts = [CodeQuestionAttempt(assessment_attempt=assessment_attempt, code_question=cq) for cq in code_questions]
        CodeQuestionAttempt.objects.bulk_create(cq_attempts)

    # queue celery task to automatically submit the attempt when duration has lapsed (30 seconds grace period)
    # ensures that the attempt is automatically submitted even if the user has closed the page
    duration = assessment_attempt.assessment.duration
    if duration != 0:  # if duration is 0 (unlimited time), no need to auto submit
        auto_submission_time = timezone.now() + timedelta(minutes=duration) + timedelta(seconds=30)
        force_submit_assessment.apply_async((assessment_attempt.id,), eta=auto_submission_time)

    return assessment_attempt


@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def attempt_question(request, assessment_attempt_id, question_index):
    # get assessment attempt
    assessment_attempt = get_object_or_404(AssessmentAttempt, id=assessment_attempt_id)

    # disallow if assessment already submitted
    if assessment_attempt.time_submitted:
        raise PermissionDenied()

    # ensure attempt belongs to user
    if assessment_attempt.candidate != request.user:
        raise PermissionDenied()

    # get question
    question_statuses, question_attempt = get_assessment_attempt_question(assessment_attempt_id, question_index)

    # if no question exist at the index, raise 404
    if not question_attempt:
        raise Http404()

    # track start time
    start_time_unformatted = timezone.localtime() - question_attempt.time_spent
    start_time = start_time_unformatted.strftime("%Y-%m-%d %H:%M:%S")

    # context
    context = {
        'assessment': assessment_attempt.assessment,
        'question_index': question_index,
        'assessment_attempt': assessment_attempt,
        'question_attempt': question_attempt,
        'question_statuses': question_statuses,
        'start_time': start_time,
    }

    # render different template depending on question type
    if isinstance(question_attempt, CodeQuestionAttempt):
        code_question = question_attempt.code_question
        code_snippets = CodeSnippet.objects.filter(code_question=code_question)
        for cs in code_snippets:
            attempt_snippet = CodeQuestionAttemptSnippet.objects.filter(cq_attempt=question_attempt, language=cs.language).first()
            if attempt_snippet:
                cs.saved_code = attempt_snippet.code
            else:
                cs.saved_code = cs.code

        last_used_language = CodeQuestionAttemptSnippet.objects.filter(cq_attempt=question_attempt).order_by('-updated_at').first()
        sample_tc = TestCase.objects.filter(code_question=code_question, sample=True).first()
        code_question_submissions = CodeQuestionSubmission.objects.filter(cq_attempt=question_attempt).order_by('-id')

        # add to base context
        context.update({
            'code_question': code_question,
            'sample_tc': sample_tc,
            'code_snippets': code_snippets,
            'last_used_language': last_used_language.language if last_used_language else None,
            'code_question_submissions': code_question_submissions,
            'is_software_language': question_attempt.code_question.is_software_language(),
        })

        # extract outputs if hardware language
        if not question_attempt.code_question.is_software_language():
            data = eval(sample_tc.stdout)
            context.update({
                'wavedrom_output': [signal['name'] for signal in data['signal'] if signal['name'].startswith('out_')]
            })
            if hasattr(code_question, 'hdlquestionconfig') and code_question.hdlquestionconfig.get_question_type() == 'Module and Testbench Design':
                context.update({
                    'tab': True,
                })

        return render(request, "attempts/question-attempt.html", context)
    elif isinstance(question_attempt, McqQuestionAttempt):
        mcq_question = question_attempt.mcq_question
        mcq_question_options = McqQuestionOption.objects.filter(mcq_question=mcq_question).order_by('id')
        mcq_question_attempt_options = McqQuestionAttemptOption.objects.filter(mcq_attempt=question_attempt).values_list('selected_option', flat=True)

        # add to base context
        context.update({
            'mcq_question': mcq_question,
            'mcq_question_options': mcq_question_options,
            'mcq_question_attempt_options': mcq_question_attempt_options
        })

        return render(request, "attempts/question-attempt.html", context)
    else:
        # should not reach here
        raise Exception("Unknown question type!")


@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def save_code_attempt_snippet(request, code_question_attempt_id):
    try:
        if request.method == "POST":
            # get assessment attempt
            code_question_attempt = get_object_or_404(CodeQuestionAttempt, id=code_question_attempt_id)

            # if no question exist at the index, raise 404
            if not code_question_attempt:
                raise Http404()

            # ensure attempt belongs to user
            if code_question_attempt.assessment_attempt.candidate != request.user:
                raise PermissionDenied()

            code = request.POST.get('code')
            judge_id = request.POST.get('lang-id')
            language = Language.objects.get(judge_language_id=judge_id)

            with transaction.atomic():
                attempt_snippet = CodeQuestionAttemptSnippet.objects.filter(cq_attempt=code_question_attempt, language=language).first()
                if attempt_snippet:
                    attempt_snippet.code = code
                else:
                    # create CodeQuestionSubmission
                    attempt_snippet = CodeQuestionAttemptSnippet.objects.create(cq_attempt=code_question_attempt, code=code, language=language)      
                attempt_snippet.save()

            context = {
                "result": "success",
            }
            return Response(context, status=status.HTTP_200_OK)
        
    except Exception as ex:
        error_context = {
            "result": "error",
            "message": f"{ex}",
        } 
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def save_mcq_attempt_options(request, mcq_question_attempt_id):
    try:
        if request.method == "POST":
            # get assessment attempt
            mcq_question_attempt = get_object_or_404(McqQuestionAttempt, id=mcq_question_attempt_id)

            # if no question exist at the index, raise 404
            if not mcq_question_attempt:
                raise Http404()

            # ensure attempt belongs to user
            if mcq_question_attempt.assessment_attempt.candidate != request.user:
                raise PermissionDenied()

            selected_option_ids = request.POST.get('selected_option_ids').split(",")       

            with transaction.atomic():
                # delete all existing McqQuestionAttemptOption
                McqQuestionAttemptOption.objects.filter(mcq_attempt=mcq_question_attempt).delete()

                for selected_option_id in selected_option_ids:
                    attempt_option = McqQuestionAttemptOption.objects.filter(mcq_attempt=mcq_question_attempt, selected_option_id=selected_option_id).first()
                    if not attempt_option:
                        # create McqQuestionAttemptOption
                        attempt_option = McqQuestionAttemptOption.objects.create(mcq_attempt=mcq_question_attempt, selected_option_id=selected_option_id)      
                    attempt_option.save()

                start_time = request.POST.get('start_time')
                current_time = timezone.localtime()
                time_spent = current_time - timezone.make_aware(datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S"))    
                mcq_question_attempt.time_spent = time_spent 
                mcq_question_attempt.save()

            context = {
                "result": "success",
            }
            return Response(context, status=status.HTTP_200_OK)
        
    except Exception as ex:
        error_context = {
            "result": "error",
            "message": f"{ex}",
        } 
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)

@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def submit_single_test_case(request, test_case_id, code_question_id):
    """
    Submits a single test case to judge0 for execution, returns the token.
    This is used for the "Compile and Run" option for users to run the sample test case.
    This submission is not stored in the database.
    """
    try:
        if request.method == "POST":
            # get test case instance
            if test_case_id != 0:
                test_case = TestCase.objects.filter(id=test_case_id).first()
                if not test_case:
                    error_context = {
                        "result": "error",
                        "message": "The specified Test Case does not exist.",
                    }
                    return Response(error_context, status=status.HTTP_404_NOT_FOUND)
            else:
                # create temporary test_case object
                test_case = TestCase()
                test_case.code_question = CodeQuestion.objects.filter(id=code_question_id).first()
                test_case.stdin = request.data.get("run_stdin")
                test_case.stdout = request.data.get("run_stdout")
                test_case.time_limit = request.data.get("run_time_limit")
                test_case.memory_limit = request.data.get("run_memory_limit")
                test_case.score = 0
                test_case.max_threads = request.data.get("run_max_threads")
                test_case.min_threads = request.data.get("run_min_threads")

            # evaluate expected_output using judge0 for custom inputs
            if request.data.get("run_stdin") != test_case.stdin:
                test_case.stdin = request.data["run_stdin"]
                expected_output_params = construct_expected_output_judge0_params(test_case)
                if expected_output_params is None:
                    context = {
                        "result": "error",
                        "message": "No solution code provided for custom test cases.",
                    }
                    return Response(context, status=status.HTTP_400_BAD_REQUEST)
                # call judge0
                url = settings.JUDGE0_URL + "/submissions/?base64_encoded=false&wait=false"
                res = requests.post(url, json=expected_output_params)
                data = res.json()

                # return error if no token
                token = data.get("token")
                if not token:
                    error_context = {
                        "result": "error",
                        "message": "Judge0 error.",
                    }
                    return Response(error_context, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                # wait for expected_output to be evaluated
                expected_output_result = check_tc_result(token)
                while expected_output_result["status_id"] in [1, 2]:
                    expected_output_result = check_tc_result(token)
                test_case.stdout = expected_output_result['stdout']

            lang_id = int(request.POST.get('lang-id'))
            if not test_case.code_question.is_software_language and test_case.code_question.hdlquestionconfig.get_question_type() == 'Module and Testbench Design':
                test_case.stdin = request.POST.get('testbench_code')
                code = request.POST.get('module_code')
            else:
                code = request.POST.get('code')
            params = construct_judge0_params(code, lang_id, test_case)
            
            # call judge0
            url = settings.JUDGE0_URL + "/submissions/?base64_encoded=false&wait=false"
            res = requests.post(url, json=params)
            data = res.json()

            # return error if no token
            token = data.get("token")
            if not token:
                error_context = {
                    "result": "error",
                    "message": "Judge0 error.",
                }
                return Response(error_context, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            context = {
                "result": "success",
                "token": token,
            }
            return Response(context, status=status.HTTP_200_OK)
    except requests.exceptions.ConnectionError:
        error_context = {
            "result": "error",
            "message": "Judge0 API seems to be down.",
        }
        return Response(error_context, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as ex:
        error_context = {
            "result": "error",
            "message": f"{ex}",
        } 
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)
    
    finally:
        # delete zip file
        if os.path.exists('submission.zip'):
            os.remove('submission.zip')


@api_view(["GET"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def get_tc_details(request):
    """
    Retrieves the status_id of a submission from Judge0, given a judge0 token.
    - Used for checking the status of a submitted sample test case => status_only=true
    - Used for viewing the details of a submitted test case (in the test case details modal) => status_only=false
    """

    try:
        if request.method == "GET":
            # get parameters from request
            status_only = request.GET.get('status_only') == 'true'
            vcd = request.GET.get('vcd') == 'true'
            token = request.GET.get('token')
            if not token:
                return Response({ "result": "error" }, status=status.HTTP_400_BAD_REQUEST)

            # call judge0
            try:
                data = check_tc_result(token, status_only, vcd)
                context = {
                    "result": "success",
                    "data": data,
                }
                return Response(context, status=status.HTTP_200_OK)

            except requests.exceptions.ConnectionError:
                error_context = {
                    "result": "error",
                    "message": "Judge0 API seems to be down.",
                }
                return Response(error_context, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except Exception as ex:
        error_context = {
            "result": "error",
            "message": f"{ex}",
        } 
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)

def check_tc_result(token, status_only = False, vcd = False):
    # friendly names of status_ids
    judge0_statuses = {
        1: "In Queue",
        2: "Processing",
        3: "Accepted",
        4: "Wrong Answer",
        5: "Time Limit Exceeded",
        6: "Compilation Error",
        7: "Runtime Error SIGSEGV",
        8: "Runtime Error SIGXFSZ",
        9: "Runtime Error SIGFPE",
        10: "Runtime Error SIGABRT",
        11: "Runtime Error NZEC",
        12: "Runtime Error Other",
        13: "Internal Error",
        14: "Exec Format Error",
        15: "Insufficient Threads Used",
        16: "Data Race Detected",
        17: "Exceeded Threads Limit",
    }
    try:
        if status_only:
            url = f"{settings.JUDGE0_URL}/submissions/{token}?base64_encoded=false&fields=status_id"
        elif vcd:
            url = f"{settings.JUDGE0_URL}/submissions/{token}?base64_encoded=false&fields=status_id,stdout,stderr,expected_output,vcd_output"
        else:
            url = f"{settings.JUDGE0_URL}/submissions/{token}?base64_encoded=false&fields=status_id,stdin,stdout,stderr,expected_output,compile_output"

        res = requests.get(url)
        data = res.json()

        # change to base64 encoding if needed
        if "error" in data:
            url = url.replace("base64_encoded=false", "base64_encoded=true")
            res = requests.get(url)
            data = res.json()
            decode_judge0_params(data, "stdout")
            decode_judge0_params(data, "stdin")
            decode_judge0_params(data, "stderr")
            decode_judge0_params(data, "expected_output")
            decode_judge0_params(data, "compile_output")

        stdout = data['stdout']
        
        # post processing for concurrency question
        test_case = TestCase.objects.filter(testcaseattempt__token=token).first()
        max_threads = test_case.max_threads if test_case else 50
        if stdout and re.match(r'AASP_\d+_THREADS_CREATED_INSUFFICIENT', stdout): 
            concurrency_results = evaluate_concurrency_results(stdout, data['expected_output'], data['status_id'], data['stderr'], max_threads)
            data["status_id"] = concurrency_results['status_id']
            data["stdout"] = concurrency_results['stdout']

        # append friendly status name
        data['status'] = judge0_statuses[int(data['status_id'])]

        # hide fields if this belongs to a hidden test case
        if TestCase.objects.filter(hidden=True, testcaseattempt__token=token).exists():
            data['stdin'] = "Hidden"
            data['stdout'] = "Hidden"
            data['expected_output'] = "Hidden"

        return data
    
    except requests.exceptions.ConnectionError:
        raise requests.exceptions.ConnectionError

@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def code_question_submission(request, code_question_attempt_id):
    """
    When user submits an answer for a code question.

    Algorithm:
    - Generates 'CodeQuestionSubmission' and 'TestCaseAttempt's and stores in the database.
    - Calls Judge0 api to submit the test cases
    - Queues celery tasks for updating the statuses of TestCaseAttempt (by polling judge0)
    """
    try:
        if request.method == "POST":
            # get cqa object
            cqa = CodeQuestionAttempt.objects.filter(id=code_question_attempt_id).first()
            if not cqa:
                error_context = {
                    "result": "error",
                    "message": "CQA does not exist.",
                }
                return Response(error_context, status=status.HTTP_404_NOT_FOUND)

            # cqa does not belong to the request user
            if cqa.assessment_attempt.candidate != request.user:
                error_context = {
                    "result": "error",
                    "message": "You do not have permissions to perform this action.",
                }
                return Response(error_context, status=status.HTTP_401_UNAUTHORIZED)

            # get test cases
            test_cases = TestCase.objects.filter(code_question__codequestionattempt=cqa)

            # generate params for judge0 call
            language_id = int(request.POST.get('lang-id'))

            # get question type
            question_type = cqa.code_question.hdlquestionconfig.get_question_type() if not cqa.code_question.is_software_language() else None

            # get code according to question type
            if question_type == 'Module and Testbench Design':
                submissions = []

                code = request.POST.get('module_code')
                testbench_code = request.POST.get('testbench_code')

                # first test case is module code, others are testbench code
                submissions.append(construct_judge0_params(testbench_code, language_id, test_cases[0]))
                submissions.extend([construct_judge0_params(code, language_id, test_case) for test_case in test_cases[1:]])
            else:
                code = request.POST.get('code')
                submissions = [construct_judge0_params(code, language_id, test_case) for test_case in test_cases]

            params = {"submissions": submissions}
            # call judge0
            try:
                url = settings.JUDGE0_URL + "/submissions/batch?base64_encoded=false"
                res = requests.post(url, json=params)
                data = res.json()
            except ConnectionError:
                error_context = {
                    "result": "error",
                    "message": "Judge0 API seems to be down.",
                }
                return Response(error_context, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            finally:
                # delete zip file
                if os.path.exists('submission.zip'):
                    os.remove('submission.zip')
            
            # retrieve tokens from judge0 response
            tokens = [x['token'] for x in data]

            with transaction.atomic():
                # create CodeQuestionSubmission
                cqs = CodeQuestionSubmission.objects.create(cq_attempt=cqa, code=code,
                                                            language=Language.objects.get(judge_language_id=language_id))

                # create TestCaseAttempts
                test_case_attempts = TestCaseAttempt.objects.bulk_create([
                    TestCaseAttempt(cq_submission=cqs, test_case=tc, token=token) for tc, token in zip(test_cases, tokens)
                ])

                start_time = request.POST.get('start_time')
                current_time = timezone.localtime()
                time_spent = current_time - timezone.make_aware(datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S"))    
                cqa.time_spent = time_spent        
                cqa.save()

            # queue celery tasks
            # for tca in test_case_attempts:
            #     for i in range(1, 6):
            #         update_test_case_attempt_status.apply_async((tca.id, tca.token), countdown=i*2)

            context = {
                "result": "success",
                "cqs_id": cqs.id,
                "time_submitted": timezone.localtime(cqs.time_submitted).strftime("%d/%m/%Y %I:%M %p"),
                "statuses": [[tca.id, tca.status, tca.token] for tca in test_case_attempts]
            }
            return Response(context, status=status.HTTP_200_OK)

    except Exception as ex:
        error_context = { 
            "result": "error",
            "message": f"{ex}",
        }
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)

def update_test_case_attempt_status(tca_id: int, token: str):
    """
    Polls judge0 to get the status_id of a single submission (one test case)
    If status_id has been changed, save the change to db.
    If the submission is still being processed, re-queue this task to be polled again later.
    """
    try:
        # call judge0
        url = f"{settings.JUDGE0_URL}/submissions/{token}?base64_encoded=false&fields=status_id,stdout,stderr,time,memory"
        res = requests.get(url)
        data = res.json()

        status_id = data.get('status_id')
        stdout = data.get('stdout')
        stderr = data.get('stderr')
        time = data.get('time')
        memory = data.get('memory')

        if status_id not in [1, 2]:
            tca = TestCaseAttempt.objects.prefetch_related('cq_submission').get(id=tca_id)
            tca.status = status_id
            tca.time = time
            tca.memory = memory
            
            # post processing for concurrency question
            if tca.test_case.code_question.is_concurrency_question:
                concurrency_results = evaluate_concurrency_results(stdout, tca.test_case.stdout, status_id, stderr, tca.test_case.max_threads)
                tca.status = concurrency_results['status_id']
                
                # save number of threads used
                tca.threads = get_max_threads_used(stdout)
                tca.thread_times = "|".join(concurrency_results['thread_times'])
            tca.stdout = stdout
            tca.save()
            # check if all test cases have been completed
            finished = not TestCaseAttempt.objects.filter(cq_submission_id=tca.cq_submission.id, status__in=[1, 2]).exists()

            # only continue if test cases are complete
            if finished:
                update_cqs_passed_flag(tca.cq_submission.id)
    except ConnectionError as e:
        print(e.message)

def update_cqs_passed_flag(cqs_id):
    """
    Checks if all test cases of a CodeQuestionSubmission has been processed by judge0.
    Update the "passed" field of the CQS instance and initiates the computation of the submission score.
    If it was already calculated previously, nothing will be done.
    """
    # # check if all test cases have been completed
    # finished = not TestCaseAttempt.objects.filter(cq_submission_id=cqs_id, status__in=[1, 2]).exists()

    # # only continue if test cases are complete
    # if finished:
    # get cqs object
    cqs = CodeQuestionSubmission.objects.get(id=cqs_id)

    # only continue if it was not previously calculated
    if cqs.passed is None:
        # update the passed flag
        passed = not TestCaseAttempt.objects.filter(cq_submission_id=cqs_id, status__range=(4, 17)).exists()
        cqs.passed = passed
        cqs.save()

@api_view(["GET"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def get_cq_submission_status(request):
    """
    Returns the statuses of each TestCaseAttempt belonging to a CodeQuestionSubmission.
    """
    try:
        if request.method == "GET":
            cq_submission_id = request.GET.get("cqs_id")

            # get test case attempts
            test_cases = list(
                TestCaseAttempt.objects.filter(cq_submission=cq_submission_id).values_list('id', 'token'))
            
            for test_case in test_cases:
                update_test_case_attempt_status(test_case[0], test_case[1])

            test_cases = list(
                TestCaseAttempt.objects.filter(cq_submission=cq_submission_id).values_list('id', 'status', 'token'))
            cqs = CodeQuestionSubmission.objects.get(id=cq_submission_id)

            # check if the cqa belongs to the request user
            if cqs.cq_attempt.assessment_attempt.candidate != request.user:
                error_context = {
                    "result": "error",
                    "message": "You do not have permissions to perform this action.",
                }
                return Response(error_context, status=status.HTTP_401_UNAUTHORIZED)
            
            context = {
                "result": "success",
                "cqs_id": cq_submission_id,
                "outcome": cqs.outcome,
                "statuses": test_cases
            }
            return Response(context, status=status.HTTP_200_OK)
    
    except Exception as ex:
        error_context = { 
            "result": "error",
            "message": f"{ex}"
        }
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)


@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def submit_assessment(request, assessment_attempt_id):
    """
    When the user submits an assessment attempt.
    """
    if request.method == "POST":
        # check permissions
        assessment_attempt = get_object_or_404(AssessmentAttempt, id=assessment_attempt_id)
        if assessment_attempt.candidate != request.user:
            raise PermissionDenied()

        # set time_submitted
        if assessment_attempt.time_submitted is None:
            assessment_attempt.auto_submit = False
            assessment_attempt.time_submitted = timezone.now()
            assessment_attempt.save()

            # queue celery task to compute the assessment attempt's score (using results from test cases)
            compute_assessment_attempt_score(assessment_attempt.id)

            messages.success(request, "Assessment submitted successfully!")

        else:
            return PermissionDenied()

        return redirect('assessment-landing', assessment_id=assessment_attempt.assessment.id)

def compute_assessment_attempt_score(assessment_attempt_id):
    """
    This task is queued when an AssessmentAttempt has been submitted (both user-initiated and server-side)
    This tasks calculates the total score of the AssessmentAttempt, and determines if it is the best attempt.
    If the AssessmentAttempt contains a submission that is still being processed, the task will be delayed.
    """
    # get the instance
    assessment_attempt = AssessmentAttempt.objects.get(id=assessment_attempt_id)
    assessment_attempt.compute_score()

@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.lab_assistant, UserGroup.student)
def upload_snapshot(request, assessment_attempt_id):
    """
    Uploads candidate snapshots to MEDIA_ROOT/<course>/<test_name>/<username>/<attempt_number>/<filename>
    when candidate snapshots are:
    1. captured as initial.png on assessment-landing page
    2. auto-captured as <timestamp>.png at randomised intervals on code-question-attempt page
    """

    try:
        if request.method == "POST":
            assessment_attempt = get_object_or_404(AssessmentAttempt, id=assessment_attempt_id)

            attempt_number = request.POST.get('attempt_number')
            timestamp = request.POST.get('timestamp')
            timestamp_tz = timezone.make_aware(datetime.strptime(timestamp, "%d-%m-%Y %H:%M:%S"))
            image = request.FILES['image']

            snapshot = CandidateSnapshot(assessment_attempt=assessment_attempt, 
                                        attempt_number=attempt_number, timestamp=timestamp_tz, image=image)
            snapshot.save()

            """ 
            if celery worker container is running on a machine that's different from dev machine, use local_detect_faces instead of detect_faces.delay.
            cannot queue as task because MEDIA_ROOT are different directories
            """
            # if settings.DEBUG:
            #     local_detect_faces(snapshot)

            detect_faces.delay(snapshot.id)

            context = {
                "faces_detected": snapshot.faces_detected,
            }
            return Response(context, status=status.HTTP_200_OK)

    except Exception as ex:
        error_context = { 
            "result": "error",
            "message": f"{ex}",
        }
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)


def local_detect_faces(snapshot):
    image_path = os.path.join(settings.MEDIA_ROOT, snapshot.image.name)

    model_pack_name = "buffalo_sc"
    app = FaceAnalysis(name=model_pack_name)
    app.prepare(ctx_id=0, det_size=(640, 640))
    image = cv2.imread(image_path)
    faces = app.get(image)

    snapshot.faces_detected = len(faces)
    snapshot.save()


@api_view(["POST"])
@renderer_classes([JSONRenderer])
def detect_faces_initial(request):
    try:
        image = request.FILES['image']
        model_pack_name = "buffalo_sc"
        app = FaceAnalysis(name=model_pack_name, root=os.path.join(settings.BASE_DIR, model_pack_name))
        app.prepare(ctx_id=0, det_size=(640, 640))
        image_bytes = image.read()
        image_np = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(image_np, cv2.IMREAD_UNCHANGED)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        faces = app.get(img)

        context = {
            "faces_detected": len(faces),
        }
        return Response(context, status=status.HTTP_200_OK)

    except Exception as ex:
        error_context = {
            "result": "error",
            "message": f"{ex}",
        }
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)

@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.lab_assistant, UserGroup.student)
def vcdrom(request):
    vcd = request.POST.get('vcd')
    if vcd:
        return render(request, 'vcdrom/vcdrom.html', {'vcd': vcd})
    else:
        error_context = {
            "result": "error",
            "message": "No vcd found.",
        }
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)