# Powered by the django_filters package: https://github.com/carltongibson/django-filter/

import django_filters

from core.models import User, CourseGroup, QuestionBank, CodeQuestion


class CourseStudentFilter(django_filters.FilterSet):

    course_group = django_filters.ModelChoiceFilter(queryset=CourseGroup.objects.none(), label="Course Group", method="filter_group")

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'course_group']

    def __init__(self, course_groups, *args, **kwargs):
        super(CourseStudentFilter, self).__init__(*args, **kwargs)
        self.filters['course_group'].queryset = course_groups
        self.filters['first_name'].lookup_expr = "icontains"
        self.filters['last_name'].lookup_expr = "icontains"
        self.filters['username'].lookup_expr = "iexact"

    @staticmethod
    def filter_group(queryset, name, value):
        return queryset.filter(enrolled_groups=value)


class QuestionBankFilter(django_filters.FilterSet):
    question_bank = django_filters.ModelChoiceFilter(queryset=QuestionBank.objects.none(), label="Question Bank", method="filter_qb")

    class Meta:
        model = CodeQuestion
        fields = ['question_bank', 'name', 'tags']

    def __init__(self, question_banks, *args, **kwargs):
        super(QuestionBankFilter, self).__init__(*args, **kwargs)
        self.filters['question_bank'].queryset = question_banks
        self.filters['name'].lookup_expr = "icontains"

    @staticmethod
    def filter_qb(queryset, name, value):
        return queryset.filter(question_bank=value)
