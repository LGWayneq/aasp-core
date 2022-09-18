from django.apps import apps
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Assessment(models.Model):
    course = models.ForeignKey("Course", null=False, blank=False, on_delete=models.PROTECT)
    name = models.CharField(max_length=150, null=False, blank=False)
    time_start = models.DateTimeField(null=True, blank=True)  # null if forever
    time_end = models.DateTimeField(null=True, blank=True)  # null if forever
    duration = models.PositiveIntegerField(null=False, blank=False)  # 0 if unlimited
    num_attempts = models.PositiveIntegerField(null=False, blank=False)  # 0 if unlimited
    instructions = models.TextField(null=False, blank=False)
    deleted = models.BooleanField(default=False)
    show_grade = models.BooleanField(default=False)
    published = models.BooleanField(default=False)
    pin = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.name}"

    @property
    def status(self):
        """
        Unpublished, Deleted, Active, Upcoming, Ended
        """
        if not self.published:
            return "Unpublished"
        elif self.deleted:
            return "Deleted"
        elif not self.time_start and not self.time_end:  # unlimited
            return "Active"
        elif self.time_start and timezone.now() < self.time_start:  # not started yet
            return "Upcoming"
        elif self.time_start and self.time_end and self.time_start <= timezone.now() <= self.time_end:
            return "Active"
        elif self.time_end and timezone.now() > self.time_end:
            return "Ended"
        else:
            return "Active"

    def is_valid(self):
        """
        Returns if an assessment is valid or not.
        - (True, ""), if assessment contains questions and questions are complete.
        - (False, <error_message>), if otherwise.
        """
        CodeQuestion = apps.get_model(app_label="core", model_name="CodeQuestion")
        code_questions = CodeQuestion.objects.filter(assessment=self)

        # ensure assessment has at least one question
        if not code_questions:
            return False, "There are no questions in the assessment."

        # ensure all code questions has at least one test case and one code snippet (language)
        for cq in code_questions:
            if cq.testcase_set.count() == 0 or cq.codesnippet_set.count() == 0:
                return False, "One or more code questions are incomplete."

        return True, ""

    @property
    def total_score(self):
        TestCase = apps.get_model(app_label="core", model_name="TestCase")
        total_score = TestCase.objects.filter(code_question__assessment=self).aggregate(Sum('score')).get("score__sum", 0)
        return total_score
