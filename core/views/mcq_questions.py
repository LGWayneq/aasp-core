from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import formset_factory, inlineformset_factory
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, renderer_classes
from rest_framework.renderers import JSONRenderer

from core.decorators import groups_allowed, UserGroup
from core.forms.question_banks import McqQuestionForm
from core.models import QuestionBank, Assessment, McqQuestion, McqQuestionOption
from core.models.questions import Tag
from core.views.utils import check_permissions_course, check_permissions_code_question, embed_inout_module, embed_inout_testbench, generate_module


@login_required()
@groups_allowed(UserGroup.educator)
def create_mcq_question(request, parent, parent_id):
    """
    For creating a new code question.
    Parent is either a Question Bank or an Assessment.
    """
    question_bank = None
    assessment = None

    # get object instance and check permissions
    if parent == "qb":
        question_bank = get_object_or_404(QuestionBank, id=parent_id)

        # the user must be the question bank's owner
        if question_bank.owner != request.user:
            return PermissionDenied("You do not have permissions to modify this question bank.")

    elif parent == "as":
        assessment = get_object_or_404(Assessment, id=parent_id)

        # the user must have permissions to the course
        if check_permissions_course(assessment.course, request.user) == 0:
            return PermissionDenied("You do not have permissions to modify this assessment.")

    else:
        raise Http404()

    # create form
    form = McqQuestionForm()

    # prepare options formset
    McqQuestionOptionFormset = inlineformset_factory(McqQuestion, McqQuestionOption, fields=('description', 'correct'), extra=1)
    mcq_question_options_formset = McqQuestionOptionFormset(prefix="mcq")
        
    if request.method == "POST":
        form = McqQuestionForm(request.POST)
        mcq_question_options_formset = McqQuestionOptionFormset(request.POST, prefix="mcq")

        if form.is_valid() and mcq_question_options_formset.is_valid():
            # check at least one option is correct
            correct = False
            for option_form in mcq_question_options_formset:
                if option_form.cleaned_data.get('correct'):
                    correct = True
                    break
            if not correct:
                messages.warning(request, "At least one option must be correct.")
            else:
                with transaction.atomic():
                    # create tags
                    tags = request.POST.get('tags')
                    tags = [t.title() for t in tags.split(",")]
                    if tags:
                        Tag.objects.bulk_create([Tag(name=t) for t in tags], ignore_conflicts=True)

                    # save mcq question
                    mcq_question = form.save()

                    # add tags to code question
                    tags = Tag.objects.filter(name__in=tags).values_list('id', flat=True)
                    mcq_question.tags.add(*tags)

                    # save mcq question options
                    mcq_question_options_formset.instance = form.save()
                    mcq_question_options_formset.save()

                    messages.success(request, "The MCQ question has been created!")
                    if mcq_question.question_bank:
                        return redirect('question-bank-details', question_bank_id=mcq_question.question_bank.id)
                    else:
                        return redirect('assessment-details', assessment_id=mcq_question.assessment.id)

    context = {
        'assessment': assessment,
        'question_bank': question_bank,
        'description_placeholder': """This editor supports **markdown**! And math equations too!

You can do this: $a \\ne 0$, and this:
$$x = {-b \pm \sqrt{b^2-4ac} \over 2a}$$

**Click preview!**""",
        'mcq_question_options_formset': mcq_question_options_formset,
        'form': form,
    }
    return render(request, 'mcq_questions/create-mcq-question.html', context)

@login_required()
@groups_allowed(UserGroup.educator)
def update_mcq_question(request, code_question_id):
    # get code question object
    mcq_question = get_object_or_404(McqQuestion, id=code_question_id)

    # check permissions
    if check_permissions_code_question(mcq_question, request.user) != 2:
        if mcq_question.question_bank:
            return PermissionDenied("You do not have permissions to modify this question bank.")
        else:
            return PermissionDenied("You do not have permissions to modify this assessment.")

    # prepare form
    form = McqQuestionForm(instance=mcq_question)

    # prepare options formset
    McqQuestionOptionFormset = inlineformset_factory(McqQuestion, McqQuestionOption, fields=('description', 'correct'), extra=1)
    mcq_question_options_formset = McqQuestionOptionFormset(instance=mcq_question, prefix="mcq")
        
    if request.method == "POST":
        form = McqQuestionForm(request.POST, instance=mcq_question)
        mcq_question_options_formset = McqQuestionOptionFormset(request.POST, instance=mcq_question, prefix="mcq")

        if form.is_valid() and mcq_question_options_formset.is_valid():
            # check at least one option is correct
            correct = False
            for option_form in mcq_question_options_formset:
                if option_form.cleaned_data.get('correct'):
                    correct = True
                    break
            if not correct:
                messages.warning(request, "At least one option must be correct.")
            else:
                with transaction.atomic():
                    # create tags
                    tags = request.POST.get('tags')
                    tags = [t.title() for t in tags.split(",")]
                    if tags:
                        Tag.objects.bulk_create([Tag(name=t) for t in tags], ignore_conflicts=True)

                    mcq_question = form.save()
                    messages.success(request, "MCQ Question successfully updated!")

                    # clear old tags and add tags to code question
                    mcq_question.tags.clear()
                    tags = Tag.objects.filter(name__in=tags).values_list('id', flat=True)
                    mcq_question.tags.add(*tags)

                    # delete previous options
                    McqQuestionOption.objects.filter(mcq_question=mcq_question).delete()

                    # save mcq question options
                    mcq_question_options_formset.save()

                    if mcq_question.question_bank:
                        return redirect('question-bank-details', question_bank_id=mcq_question.question_bank.id)
                    else:
                        return redirect('assessment-details', assessment_id=mcq_question.assessment.id)
        
    context = {
        'mcq_question': mcq_question,
        'mcq_question_options_formset': mcq_question_options_formset,
        'form': form,
    }
    return render(request, 'mcq_question/update-mcq-question.html', context)