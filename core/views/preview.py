from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render
from rest_framework.decorators import api_view

from core.decorators import groups_allowed, UserGroup
from core.models import CodeQuestion, McqQuestion, McqQuestionOption
from core.models.questions import TestCase, CodeSnippet
from core.views.utils import get_question_instance

@api_view(["GET"])
@login_required()
@groups_allowed(UserGroup.educator)
def preview_question(request, question_id):
    # get question
    question = get_question_instance(question_id)

    # if no question exist at the index, raise 404
    if not question:
        raise Http404()

    if isinstance(question, CodeQuestion):
        code_snippets = CodeSnippet.objects.filter(code_question=question)
        sample_tc = TestCase.objects.filter(code_question=question, sample=True).first()
        hidden_tc_stdin = list(TestCase.objects.filter(code_question=question, sample=False).values_list('stdin', flat=True))

        # context
        context = {
            'code_question': question,
            'code_snippets': code_snippets,
            'sample_tc': sample_tc,
            'hidden_tc_stdin': hidden_tc_stdin,
            'is_software_language': question.is_software_language(),
        }
    elif isinstance(question, McqQuestion):
        mcq_question_options = McqQuestionOption.objects.filter(mcq_question=question).order_by('id')

        # add to base context
        context = {
            'mcq_question': question,
            'mcq_question_options': mcq_question_options,
        }

    return render(request, "preview/preview-question.html", context)