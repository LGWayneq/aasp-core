from django.contrib.auth.decorators import login_required
from django.forms import models
from django import forms
from core.models import Assessment


class AssessmentForm(models.ModelForm):
    require_pin = forms.BooleanField(initial=False, required=False)

    class Meta:
        model = Assessment
        fields = ['course', 'name', 'time_start', 'time_end', 'duration', 'num_attempts', 'instructions', 'show_grade',\
                'require_webcam', 'limit_tab_switching', 'weightage']

    def __init__(self, courses, *args, **kwargs):
        super(AssessmentForm, self).__init__(*args, **kwargs)
        self.fields['course'].queryset = courses
        self.fields['require_pin'].initial = self.instance.pin is not None

    def clean(self):
        cleaned_data = super().clean()

        if cleaned_data['time_start'] and cleaned_data['time_end']:
            if cleaned_data['time_start'] > cleaned_data['time_end']:
                raise forms.ValidationError("Start data/time must be before end date/time.")
