from datetime import timedelta, datetime

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
from core.models import Assessment, AssessmentAttempt, CodeQuestionAttempt, CodeQuestion, TestCase, CodeSnippet, \
    CodeQuestionSubmission, TestCaseAttempt, Language, CandidateSnapshot
from core.tasks import update_test_case_attempt_status, force_submit_assessment, compute_assessment_attempt_score, \
    detect_faces
from core.views.utils import get_assessment_attempt_question, check_permissions_course, user_enrolled_in_course, construct_judge0_params, vcd2wavedrom


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

        # generate a cq_attempt for each code question in the assessment
        code_questions = CodeQuestion.objects.filter(assessment=assessment).order_by('id')
        cq_attempts = [CodeQuestionAttempt(assessment_attempt=assessment_attempt, code_question=cq) for cq in
                       code_questions]
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

    # context
    context = {
        'question_index': question_index,
        'assessment_attempt': assessment_attempt,
        'question_attempt': question_attempt,
        'question_statuses': question_statuses,
        'is_software_language': question_attempt.code_question.is_software_language(),
    }

    # render different template depending on question type (currently only CodeQuestion)
    if isinstance(question_attempt, CodeQuestionAttempt):
        code_question = question_attempt.code_question
        code_snippets = CodeSnippet.objects.filter(code_question=code_question)
        sample_tc = TestCase.objects.filter(code_question=code_question, sample=True).first()
        code_question_submissions = CodeQuestionSubmission.objects.filter(cq_attempt=question_attempt).order_by('-id')

        # add to base context
        context.update({
            'code_question': code_question,
            'sample_tc': sample_tc,
            'code_snippets': code_snippets,
            'code_question_submissions': code_question_submissions,
        })

        # extract outputs if hardware language
        if not question_attempt.code_question.is_software_language():
            data = eval(sample_tc.stdout)
            context.update({
                'wavedrom_output': [signal['name'] for signal in data['signal'] if signal['name'].startswith('out_')]
            })

        return render(request, "attempts/code-question-attempt.html", context)

    else:
        # should not reach here
        raise Exception("Unknown question type!")


@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.student)
def submit_single_test_case(request, test_case_id):
    """
    Submits a single test case to judge0 for execution, returns the token.
    This is used for the "Compile and Run" option for users to run the sample test case.
    This submission is not stored in the database.
    """
    try:
        if request.method == "POST":
            # get test case instance
            test_case = TestCase.objects.filter(id=test_case_id).first()
            if not test_case:
                error_context = {
                    "result": "error",
                    "message": "The specified Test Case does not exist.",
                }
                return Response(error_context, status=status.HTTP_404_NOT_FOUND)

            test_case.stdin = request.data["run_stdin"]
            params = construct_judge0_params(request, test_case)

            # call judge0
            try:
                url = settings.JUDGE0_URL + "/submissions/?base64_encoded=false&wait=false"
                res = requests.post(url, json=params)
                data = res.json()
            except requests.exceptions.ConnectionError:
                error_context = {
                    "result": "error",
                    "message": "Judge0 API seems to be down.",
                }
                return Response(error_context, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
    }

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
                if status_only:
                    url = f"{settings.JUDGE0_URL}/submissions/{token}?base64_encoded=false&fields=status_id"
                elif vcd:
                    url = f"{settings.JUDGE0_URL}/submissions/{token}?base64_encoded=false&fields=status_id,stdout,stderr,expected_output,vcd_output"
                else:
                    url = f"{settings.JUDGE0_URL}/submissions/{token}?base64_encoded=false&fields=status_id,stdin,stdout,expected_output,compile_output"

                res = requests.get(url)
                data = res.json()

                # append friendly status name
                data['status'] = judge0_statuses[int(data['status_id'])]

                # hide fields if this belongs to a hidden test case
                if TestCase.objects.filter(hidden=True, testcaseattempt__token=token).exists():
                    data['stdin'] = "Hidden"
                    data['stdout'] = "Hidden"
                    data['expected_output'] = "Hidden"

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
            code = request.POST.get('code')
            language_id = request.POST.get('lang-id')
            submissions = [construct_judge0_params(request, test_case) for test_case in test_cases]
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

            # queue celery tasks
            for tca in test_case_attempts:
                update_test_case_attempt_status.delay(tca.id, tca.token, 1)

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
            statuses = list(
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
                "statuses": statuses
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
            compute_assessment_attempt_score.delay(assessment_attempt.id)

            messages.success(request, "Assessment submitted successfully!")

        else:
            return PermissionDenied()

        return redirect('assessment-landing', assessment_id=assessment_attempt.assessment.id)


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
        app = FaceAnalysis(name=model_pack_name)
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
    
@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.lab_assistant, UserGroup.student)
def wavedrom(request):
    vcd = request.POST.get('vcd')
    if vcd:
        return Response({'wavedrom': vcd2wavedrom(vcd)}, status=status.HTTP_200_OK)
    else:
        error_context = {
            "result": "error",
            "message": "No vcd found.",
        }
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)