from django.contrib.auth.decorators import login_required
from django.forms import models
from django.db.models import Sum
from django import forms
from core.models import Assessment


class AssessmentForm(models.ModelForm):
    require_pin = forms.BooleanField(initial=False, required=False)
    weightage = forms.IntegerField(initial=0, min_value=0, max_value=100)

    class Meta:
        model = Assessment
        fields = ['course', 'name', 'time_start', 'time_end', 'duration', 'num_attempts', 'instructions', 'show_grade',\
                'require_webcam', 'limit_tab_switching', 'weightage']

    def __init__(self, courses, *args, **kwargs):
        super(AssessmentForm, self).__init__(*args, **kwargs)
        self.fields['course'].queryset = courses
        self.fields['require_pin'].initial = self.instance.pin is not None
        self.fields['weightage'].initial = self.instance.weightage if self.instance else 0

    def clean(self):
        cleaned_data = super().clean()

        if cleaned_data['time_start'] and cleaned_data['time_end']:
            if cleaned_data['time_start'] > cleaned_data['time_end']:
                raise forms.ValidationError("Start data/time must be before end date/time.")
            
        if cleaned_data['weightage']:
            prev_weightage = self.initial.get('weightage', 0)
            total_weightage = Assessment.objects.filter(course=self.cleaned_data['course'], deleted=False).aggregate(Sum('weightage'))['weightage__sum']
            weightage_without_this = total_weightage - prev_weightage if total_weightage else 0

            if weightage_without_this + self.cleaned_data['weightage'] > 100:
                raise forms.ValidationError('Total weightage of assessments in the course cannot be more than 100%. Current maximum allowed weightage: ' + str(100 - weightage_without_this) + '%.')