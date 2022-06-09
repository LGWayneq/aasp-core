from django.forms import models

from core.models import QuestionBank
from core.models.questions import TestCase, CodeQuestion


class QuestionBankForm(models.ModelForm):
    class Meta:
        model = QuestionBank
        fields = ['name', 'description', 'private']


class CodeQuestionForm(models.ModelForm):
    class Meta:
        model = CodeQuestion
        fields = ['name', 'description', 'question_bank', 'assessment']

