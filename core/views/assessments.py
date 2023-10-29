import random

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, renderer_classes
from rest_framework.renderers import JSONRenderer

from core.decorators import groups_allowed, UserGroup
from core.filters import QuestionBankFilter
from core.forms.assessments import AssessmentForm
from core.models import Course, Assessment, CodeQuestion, McqQuestion, McqQuestionOption, TestCase, CodeSnippet, Tag, QuestionBank
from core.serializers import CodeQuestionsSerializer, McqQuestionSerializer
from core.views.utils import check_permissions_course, check_permissions_assessment, check_permissions_question, \
    construct_assessment_published_email


@login_required()
@groups_allowed(UserGroup.educator, UserGroup.lab_assistant)
def view_assessments(request):
    # retrieve courses for this user
    courses = Course.objects.filter(Q(owner=request.user) | Q(maintainers=request.user)).distinct().prefetch_related(
        'owner', 'maintainers')
    assessments = Assessment.objects.filter(course__in=courses).prefetch_related('course')

    deleted_assessments = assessments.filter(deleted=True)
    assessments = assessments.filter(deleted=False)

    now = timezone.now()
    # Filter assessments based on time_end
    active_assessments = assessments.filter(Q(time_end__gte=now) | Q(time_end__isnull=True))
    inactive_assessments = assessments.filter(time_end__lt=now)

    context = {
        "active_assessments": active_assessments,
        "inactive_assessments": inactive_assessments,
        "deleted_assessments": deleted_assessments,
        "assessments": assessments
    }
    return render(request, 'assessments/assessments.html', context)

@login_required()
@groups_allowed(UserGroup.educator)
def create_assessment(request):
    # get course_id if exists (optional)
    course_id = request.GET.get('course_id')

    # retrieve courses for this user
    courses = Course.objects.filter(Q(owner=request.user) | Q(maintainers=request.user)).distinct().prefetch_related(
        'owner', 'maintainers')

    # form
    form = AssessmentForm(courses=courses, initial={'course': course_id})

    # process POST request
    if request.method == "POST":
        form = AssessmentForm(courses, request.POST)

        if form.is_valid():
            # get course object
            course = get_object_or_404(Course, id=form.data['course'])

            # check permissions before saving form
            if check_permissions_course(course, request.user) == 0:
                raise PermissionDenied("You do not have permissions for this course.")

            assessment = form.save(commit=False)
            if form.cleaned_data['require_pin'] is False:  # remove pin
                assessment.pin = None
            else:
                assessment.pin = random.randint(100_000, 999_999)  # generate random 6-digit pin
            assessment.save()

            # redirect
            messages.success(request, "The assessment has been successfully created! You can now add questions to it.")
            return redirect('assessment-details', assessment_id=assessment.id)

    context = {
        'form': form,
    }

    return render(request, 'assessments/create-assessment.html', context)


@login_required()
@groups_allowed(UserGroup.educator)
def update_assessment(request, assessment_id):
    # retrieve courses for this user
    courses = Course.objects.filter(Q(owner=request.user) | Q(maintainers=request.user)).distinct().prefetch_related(
        'owner', 'maintainers')

    # get assessment
    assessment = get_object_or_404(Assessment, id=assessment_id)

    # check permissions
    if check_permissions_assessment(assessment, request.user) == 0:
        raise PermissionDenied("You do not have permissions for this course.")

    # form
    form = AssessmentForm(courses=courses, instance=assessment)
        
    if request.method == "POST":
        form = AssessmentForm(courses, request.POST, instance=assessment)
        if form.is_valid():
            # get course object
            course = get_object_or_404(Course, id=form.data['course'])

            # check permissions before saving form
            if check_permissions_course(course, request.user) == 0:
                raise PermissionDenied("You do not have permissions for this course.")

            # update pin
            assessment = form.save(commit=False)
            if form.cleaned_data['require_pin'] is False:  # remove pin
                assessment.pin = None

            # only generate new pin if it was previously not required
            elif form.cleaned_data['require_pin'] is True and assessment.pin is None:
                assessment.pin = random.randint(100_000, 999_999)  # generate random 6-digit pin

            assessment.save()

            # redirect
            messages.success(request, "The assessment has been successfully updated!")
            return redirect('assessment-details', assessment_id=assessment.id)
        
    context = {
        'form': form,
        'assessment': assessment,
    }
    return render(request, 'assessments/update-assessment.html', context)

@login_required()
@groups_allowed(UserGroup.educator, UserGroup.lab_assistant)
def assessment_details(request, assessment_id):
    # get assessment object
    assessment = get_object_or_404(Assessment, id=assessment_id)

    # check permissions
    if check_permissions_assessment(assessment, request.user) == 0:
        raise PermissionDenied("You do not have permissions to view this assessment.")

    # get all question banks accessible by this user
    all_question_banks = QuestionBank.objects.filter(
        Q(owner=request.user) | Q(shared_with=request.user, private=True) | Q(private=False)).distinct()

    # get all tags
    tags = Tag.objects.all()

    context = {
        'assessment': assessment,
        'all_question_banks': all_question_banks,
        'tags': tags,
    }

    return render(request, 'assessments/assessment-details.html', context)


@api_view(["GET"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator)
def get_code_questions(request):
    """
    Used in the Assessment Details page for educators to clone questions from question banks into assessments.
    """
    try:
        if request.method == "GET":
            # get all question banks accessible by this user
            all_question_banks = QuestionBank.objects.filter(
                Q(owner=request.user) | Q(shared_with=request.user, private=True) | Q(private=False)).distinct()

            # get all code questions accessible by this user
            all_code_questions = CodeQuestion.objects.filter(question_bank__in=all_question_banks)
            code_question_filter = QuestionBankFilter(all_question_banks, request.GET, queryset=all_code_questions)

            # serialize filtered queryset
            code_questions = CodeQuestionsSerializer(code_question_filter.qs, many=True)

            context = {
                "result": "success",
                "code_questions": code_questions.data,
            }
            return Response(context, status=status.HTTP_200_OK)
    
    except Exception as ex:
        error_context = { 
            "result": "error",
            "message": f"{ex}" 
        } 
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)
    

@api_view(["GET"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator)
def get_mcq_questions(request):
    """
    Used in the Assessment Details page for educators to clone questions from question banks into assessments.
    """
    try:
        if request.method == "GET":
            # get all question banks accessible by this user
            all_question_banks = QuestionBank.objects.filter(
                Q(owner=request.user) | Q(shared_with=request.user, private=True) | Q(private=False)).distinct()

            # get all mcq questions accessible by this user
            all_mcq_questions = McqQuestion.objects.filter(question_bank__in=all_question_banks)
            mcq_question_filter = QuestionBankFilter(all_question_banks, request.GET, queryset=all_mcq_questions)

            # serialize filtered queryset
            mcq_questions = McqQuestionSerializer(mcq_question_filter.qs, many=True)

            context = {
                "result": "success",
                "mcq_questions": mcq_questions.data,
            }
            return Response(context, status=status.HTTP_200_OK)
    
    except Exception as ex:
        error_context = { 
            "result": "error",
            "message": f"{ex}" 
        } 
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)



@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator)
def add_code_question_to_assessment(request):
    try:
        if request.method == "POST":
            # generic error response
            error_context = { "result": "error", }

            # get assessment object
            assessment = Assessment.objects.filter(id=request.POST.get('assessment_id')).first()
            if assessment is None:
                return Response(error_context, status=status.HTTP_404_NOT_FOUND)

            # check permissions
            if check_permissions_assessment(assessment, request.user) == 0:
                return Response(error_context, status=status.HTTP_401_UNAUTHORIZED)

            # disallow if assessment is already published
            if assessment.published:
                return Response(error_context, status=status.HTTP_403_FORBIDDEN)

            # get question (ensure only objects from question banks are allowed)
            code_question_id = request.POST.get('code_question_id')
            code_question = CodeQuestion.objects.filter(id=code_question_id, assessment__isnull=True,
                                                        question_bank__isnull=False).first()
            if code_question is None:
                return Response(error_context, status=status.HTTP_404_NOT_FOUND)

            tags = code_question.tags.all()

            # check permissions (need at least Read permissions to clone)
            if check_permissions_question(code_question, request.user) == 0:
                return Response(error_context, status=status.HTTP_401_UNAUTHORIZED)

            with transaction.atomic():
                # duplicate and link code question
                code_question.pk = None
                code_question.question_bank = None  # remove link to qb
                code_question.assessment = assessment  # link to current assessment
                code_question.save()

                # duplicate and link test cases
                test_cases = TestCase.objects.filter(code_question=code_question_id)
                for tc in test_cases:
                    tc.pk = None
                    tc.code_question = code_question
                    tc.save()

                # duplicate and link code snippets
                code_snippets = CodeSnippet.objects.filter(code_question=code_question_id)
                for cs in code_snippets:
                    cs.pk = None
                    cs.code_question = code_question
                    cs.save()

                # duplicate and link tags (M2M)
                for t in tags:
                    code_question.tags.add(t.id)

                # remove past assessment attempts
                assessment.assessmentattempt_set.all().delete()

            context = { "result": "success" }
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
@groups_allowed(UserGroup.educator)
def add_mcq_question_to_assessment(request):
    try:
        if request.method == "POST":
            # generic error response
            error_context = { "result": "error", }

            # get assessment object
            assessment = Assessment.objects.filter(id=request.POST.get('assessment_id')).first()
            if assessment is None:
                return Response(error_context, status=status.HTTP_404_NOT_FOUND)

            # check permissions
            if check_permissions_assessment(assessment, request.user) == 0:
                return Response(error_context, status=status.HTTP_401_UNAUTHORIZED)

            # disallow if assessment is already published
            if assessment.published:
                return Response(error_context, status=status.HTTP_403_FORBIDDEN)

            # get question (ensure only objects from question banks are allowed)
            mcq_question_id = request.POST.get('mcq_question_id')
            mcq_question = McqQuestion.objects.filter(id=mcq_question_id, assessment__isnull=True,
                                                        question_bank__isnull=False).first()
            if mcq_question is None:
                return Response(error_context, status=status.HTTP_404_NOT_FOUND)

            tags = mcq_question.tags.all()

            # check permissions (need at least Read permissions to clone)
            if check_permissions_question(mcq_question, request.user) == 0:
                return Response(error_context, status=status.HTTP_401_UNAUTHORIZED)

            with transaction.atomic():
                # duplicate and link mcq question
                mcq_question.pk = None
                mcq_question.question_bank = None  # remove link to qb
                mcq_question.assessment = assessment  # link to current assessment
                mcq_question.save()

                # duplicate and link mcq options
                mcq_options = McqQuestionOption.objects.filter(mcq_question=mcq_question_id)
                for option in mcq_options:
                    option.pk = None
                    option.mcq_question = mcq_question
                    option.save()

                # duplicate and link tags (M2M)
                for t in tags:
                    mcq_question.tags.add(t.id)

                # remove past assessment attempts
                assessment.assessmentattempt_set.all().delete()

            context = { "result": "success" }
            return Response(context, status=status.HTTP_200_OK)

    except Exception as ex:
        error_context = {
            "result": "error",
            "message": f"{ex}",
        } 
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)


@login_required()
@groups_allowed(UserGroup.educator)
def publish_assessment(request, assessment_id):
    if request.method == "POST":
        # get assessment object
        assessment = get_object_or_404(Assessment, id=assessment_id)

        # check permissions
        if check_permissions_assessment(assessment, request.user) == 0:
            raise PermissionDenied("You do not have permissions to modify this assessment.")

        if not assessment.published:
            # check if all questions are valid
            publishable, msg = assessment.is_valid()
            if not publishable:
                messages.warning(request, f"Not published! {msg}")
                return redirect("assessment-details", assessment_id=assessment_id)

            try:
                with transaction.atomic():
                    # delete attempts
                    assessment.assessmentattempt_set.all().delete()

                    # publish assessment
                    assessment.published = True
                    assessment.save()
            
                # send email notification to students enrolled
                construct_assessment_published_email(assessment)
                messages.success(request, "The assessment is successfully published! Students have been notified of this assessment via email.")
            except Exception as ex:
                messages.warning(request, f"{ex}")

        else:
            messages.warning(request, "The assessment is already published!")
            
        return redirect("assessment-details", assessment_id=assessment_id)


@login_required()
@groups_allowed(UserGroup.educator)
def delete_assessment(request, assessment_id):
    if request.method == "POST":
        # get assessment
        assessment = get_object_or_404(Assessment, id=assessment_id)

        # check permissions (only course owner/maintainer can delete)
        if check_permissions_assessment(assessment, request.user) == 0:
            raise PermissionDenied("You do not have permissions to modify this assessment.")
        else:
            if assessment.deleted:
                messages.warning(request, "Assessment was already deleted!")
            else:
                assessment.deleted = True
                assessment.save()
                messages.success(request, "Assessment successfully deleted!")
            return redirect('assessment-details', assessment_id=assessment_id)


@login_required()
@groups_allowed(UserGroup.educator)
def undo_delete_assessment(request, assessment_id):
    if request.method == "POST":
        # get assessment
        assessment = get_object_or_404(Assessment, id=assessment_id)

        # check permissions (only course owner/maintainer can delete)
        if check_permissions_assessment(assessment, request.user) == 0:
            raise PermissionDenied("You do not have permissions to modify this assessment.")
        else:
            if assessment.deleted is False:
                messages.warning(request, "Assessment was not deleted, no undo needed!")
            else:
                assessment.deleted = False
                assessment.save()
                messages.success(request, "Undo delete successful!")
            return redirect('assessment-details', assessment_id=assessment_id)

