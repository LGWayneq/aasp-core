from django.apps import apps
from django.db import models
from django.db.models import Sum, Max


class AssessmentAttempt(models.Model):
    candidate = models.ForeignKey("User", null=False, blank=False, on_delete=models.PROTECT)
    assessment = models.ForeignKey("Assessment", null=False, blank=False, on_delete=models.PROTECT)
    time_started = models.DateTimeField(auto_now_add=True)
    time_submitted = models.DateTimeField(blank=True, null=True)
    auto_submit = models.BooleanField(blank=True, null=True)
    score = models.PositiveIntegerField(blank=True, null=True)
    best_attempt = models.BooleanField(blank=True, null=True)

    def status(self):
        if self.time_started and not self.time_submitted:
            return "Ongoing"
        elif self.score is None:
            return "Processing"
        else:
            assert self.time_started is not None
            assert self.time_submitted is not None
            assert self.score is not None
            return "Finished"

    def compute_score(self):
        TestCase = apps.get_model(app_label="core", model_name="TestCase")

        # compute the total score of all CodeQuestionAttempts (i.e. total score of this AssessmentAttempt)
        total_score = 0
        for cqa in self.codequestionattempt_set.all():
            # find the max CodeQuestionSubmission for this CodeQuestionAttempt
            max_score = 0
            for cqs in CodeQuestionSubmission.objects.filter(cq_attempt=cqa):
                cqs_score = TestCase.objects.filter(testcaseattempt__cq_submission=cqs, testcaseattempt__status=3).aggregate(Sum('score')).get(
                    "score__sum")
                cqs_score = cqs_score if cqs_score else 0
                if cqs_score > max_score:
                    max_score = cqs_score

            # add to total
            total_score += max_score

        self.score = total_score

        # get the previous best attempt
        prev_best_attempt = AssessmentAttempt.objects.filter(candidate=self.candidate, assessment=self.assessment, best_attempt=True).first()

        # check the previous_best_attempt
        if prev_best_attempt:
            if self.score > prev_best_attempt.score:
                prev_best_attempt.best_attempt = False
                prev_best_attempt.save()
                self.best_attempt = True
            else:
                self.best_attempt = False
        else:
            self.best_attempt = True

        self.save()

    def has_processing_submission(self):
        """
        Checks if this AssessmentAttempt still has CodeQuestionSubmissions that are still processing
        """
        return CodeQuestionSubmission.objects.filter(cq_attempt__assessment_attempt=self, passed=None).exists()

    @property
    def duration(self):
        if self.time_submitted is None:
            return None
        seconds = (self.time_submitted - self.time_started).total_seconds()

        if seconds < 60:
            return f"{round(seconds)} sec"
        else:
            return f"{round(seconds/60)} min"

    @property
    def total_attempts(self):
        return AssessmentAttempt.objects.filter(assessment=self.assessment, candidate=self.candidate).count()


class CodeQuestionAttempt(models.Model):
    assessment_attempt = models.ForeignKey("AssessmentAttempt", null=False, blank=False, on_delete=models.CASCADE)
    code_question = models.ForeignKey("CodeQuestion", null=False, blank=False, on_delete=models.PROTECT)

    @property
    def attempted(self):
        """
        Checks if this CQA has been attempted (has at least one submission)
        """
        return CodeQuestionSubmission.objects.filter(cq_attempt=self).exists()


class CodeQuestionSubmission(models.Model):
    cq_attempt = models.ForeignKey("CodeQuestionAttempt", null=False, blank=False, on_delete=models.CASCADE)
    time_submitted = models.DateTimeField(auto_now_add=True)
    passed = models.BooleanField(blank=True, null=True)
    language = models.ForeignKey("Language", null=False, blank=False, on_delete=models.PROTECT)
    code = models.TextField()

    @property
    def outcome(self):
        if self.passed is None:
            return "Processing"
        elif self.passed:
            return "Passed"
        elif not self.passed:
            return "Failed"

    @property
    def score(self):
        TestCase = apps.get_model(app_label="core", model_name="TestCase")
        cqs_score = TestCase.objects.filter(testcaseattempt__cq_submission=self, testcaseattempt__status=3).aggregate(Sum('score')).get("score__sum")
        cqs_score = cqs_score if cqs_score else 0
        return cqs_score


class TestCaseAttempt(models.Model):
    STATUSES = [
        (1, "In Queue"),
        (2, "Processing"),
        (3, "Accepted"),
        (4, "Wrong Answer"),
        (5, "Time Limit Exceeded"),
        (6, "Compilation Error"),
        (7, "Runtime Error (SIGSEGV)"),
        (8, "Runtime Error (SIGXFSZ)"),
        (9, "Runtime Error (SIGFPE)"),
        (10, "Runtime Error (SIGABRT)"),
        (11, "Runtime Error (NZEC)"),
        (12, "Runtime Error (Other)"),
        (13, "Internal Error"),
        (14, "Exec Format Error"),
    ]

    cq_submission = models.ForeignKey("CodeQuestionSubmission", null=False, blank=False, on_delete=models.CASCADE)
    test_case = models.ForeignKey("TestCase", null=False, blank=False, on_delete=models.PROTECT)
    token = models.CharField(max_length=36, null=False, blank=False)
    status = models.IntegerField(choices=STATUSES, default=1)
    stdout = models.TextField(blank=True, null=True)
    time = models.FloatField(blank=True, null=True)
    memory = models.FloatField(blank=True, null=True)
