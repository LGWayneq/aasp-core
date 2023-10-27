from django.core.validators import FileExtensionValidator
from django import forms

from core.models import QuestionBank
from core.models.questions import HDLQuestionSolution, TestCase, CodeQuestion, McqQuestion, HDLQuestionConfig


class QuestionBankForm(forms.ModelForm):
    class Meta:
        model = QuestionBank
        fields = ['name', 'description', 'private']


class CodeQuestionForm(forms.ModelForm):
    class Meta:
        model = CodeQuestion
        fields = ['name', 'description', 'question_bank', 'assessment', 'is_concurrency_question', 'solution_code', 'solution_code_language']


class McqQuestionForm(forms.ModelForm):
    class Meta:
        model = McqQuestion
        fields = ['name', 'description', 'question_bank', 'assessment', 'score', 'multiple_answers']


class ImportQuestionBankForm(forms.Form):
    file = forms.FileField(
        validators=[FileExtensionValidator(allowed_extensions=['json'])]
    )

class QuestionTypeForm(forms.ModelForm):
    class Meta:
        model = HDLQuestionConfig
        fields = ['question_type']
        widgets = {
            'question_type': forms.RadioSelect(attrs={'class': 'form-check-input'}),
        }

class QuestionSolutionForm(forms.ModelForm):
    class Meta:
        model = HDLQuestionSolution
        fields = ['module', 'testbench']

class ModuleGenerationForm(forms.Form):
    def clean(self):
        cleaned_data = super().clean()
        error = {}

        msb = cleaned_data.get('msb')
        lsb = cleaned_data.get('lsb')

        if msb is not None and lsb is not None and msb < lsb:
            error['msb'] = 'MSB cannot be less than LSB'
            error['lsb'] = 'LSB cannot be greater than MSB'

        # Check if this is the first form in the formset
        if self.prefix == 'module-0':
            module_name = cleaned_data.get('module_name')
            if not module_name:
                error['module_name'] = 'Module name cannot be empty'

        if error:
            raise forms.ValidationError(error)

        return cleaned_data
    
    PORTS = [
        ('input', 'input'),
        ('output', 'output'),
        ('inout', 'inout'),
    ]

    module_name = forms.CharField(
        label='Module Name',
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control my-3'})
    )

    port_name = forms.CharField(
        label='Port Name',
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    port_direction = forms.ChoiceField(
        label='Port Direction',
        choices=PORTS,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    bus = forms.BooleanField(
        label='Bus',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    msb = forms.IntegerField(
        label='MSB',
        required=False,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'disabled': 'true', 'onblur': 'checkValue(this)', 'value': '0'})
    )

    lsb = forms.IntegerField(
        label='LSB',
        required=False,
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'disabled': 'true', 'onblur': 'checkValue(this)', 'value': '0'})
    )

