from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum

from core.models import User, Assessment


class Tag(models.Model):
    class Meta:
        pass

    name = models.CharField(max_length=50, blank=False, null=False, unique=True)

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        self.name = self.name.title()


class Language(models.Model):
    name = models.CharField(max_length=50, blank=False, null=False, unique=True)
    judge_language_id = models.IntegerField(blank=False, null=False, unique=True)
    ace_mode = models.CharField(max_length=50, blank=False, null=False)
    software_language = models.BooleanField(null=False, blank=False, default=True)
    concurrency_support = models.BooleanField(null=False, blank=False, default=False)
    
    def clean(self):
        super().clean()
        self.name = self.name.upper()

    def __str__(self):
        return self.name

    def default_template(self):
        return self.codetemplate_set.first()


class QuestionBank(models.Model):
    class Meta:
        pass

    name = models.CharField(max_length=50, blank=False, null=False)
    description = models.TextField(blank=False, null=False)
    owner = models.ForeignKey(User, blank=True, null=True, on_delete=models.SET_NULL, related_name="owned_qbs")
    private = models.BooleanField(default=True, blank=False, null=False)
    shared_with = models.ManyToManyField(User, blank=True, related_name="qbs_shared_with_me")

    def __str__(self):
        return self.name

class CodeQuestion(models.Model):
    class Meta:
        pass

    name = models.CharField(max_length=50, blank=False, null=False)
    description = models.TextField(blank=False, null=False)
    tags = models.ManyToManyField(Tag, blank=True)
    is_concurrency_question = models.BooleanField(default=False, blank=False, null=False)
    solution_code = models.TextField(null=True, blank=True)
    solution_code_language = models.ForeignKey(Language, null=True, blank=True, on_delete=models.CASCADE)

    # foreign keys (either linked to a QuestionBank or Assessment instance)
    question_bank = models.ForeignKey(QuestionBank, null=True, blank=True, on_delete=models.CASCADE)
    assessment = models.ForeignKey(Assessment, null=True, blank=True, on_delete=models.PROTECT)

    def clean(self):
        """
        Custom validation to ensure at least one foreign key is not null, but not both.
        """
        if not self.question_bank and not self.assessment:
            raise ValidationError("The question must be linked to either a Question Bank or an Assessment instance.")
        elif self.question_bank and self.assessment:
            raise ValidationError("The question cannot be be linked to both a Question Bank and an Assessment instance.")

    def __str__(self):
        return self.name

    def max_score(self):
        total = self.testcase_set.all().aggregate(Sum('score')).get('score__sum')
        if total is None:
            total = 0
        return total

    def languages(self):
        return Language.objects.filter(codesnippet__code_question=self)
    
    def is_software_language(self):
        """
        Sets software language as default language if no language is set.
        """
        language_exists = Language.objects.filter(codesnippet__code_question=self).exists()
        if language_exists:
            return Language.objects.filter(codesnippet__code_question=self).first().software_language
        else:
            return True

class McqQuestion(models.Model):
    class Meta:
        pass

    name = models.CharField(max_length=50, blank=False, null=False)
    description = models.TextField(blank=False, null=False)
    tags = models.ManyToManyField(Tag, blank=True)
    score = models.PositiveIntegerField(blank=False, null=False)
    multiple_answers = models.BooleanField(default=False, blank=False, null=False)

    # foreign keys (either linked to a QuestionBank or Assessment instance)
    question_bank = models.ForeignKey(QuestionBank, null=True, blank=True, on_delete=models.CASCADE)
    assessment = models.ForeignKey(Assessment, null=True, blank=True, on_delete=models.PROTECT)

    def clean(self):
        """
        Custom validation to ensure at least one foreign key is not null, but not both.
        """
        if not self.question_bank and not self.assessment:
            raise ValidationError("The question must be linked to either a Question Bank or an Assessment instance.")
        elif self.question_bank and self.assessment:
            raise ValidationError("The question cannot be be linked to both a Question Bank and an Assessment instance.")
        
    def max_score(self):
        return self.score
        
class McqQuestionOption(models.Model):
    class Meta:
        pass

    mcq_question = models.ForeignKey(McqQuestion, null=False, blank=False, on_delete=models.CASCADE)
    content = models.CharField(max_length=100, blank=False, null=False)
    correct = models.BooleanField(default=False, blank=False, null=False)

    def clean(self):
        """
        Custom validation to ensure at least one foreign key is not null, but not both.
        """
        if not self.mcq_question:
            raise ValidationError("The MCQ choice must be linked to a MCQ Question instance.")

class CodeSnippet(models.Model):
    class Meta:
        pass

    code_question = models.ForeignKey(CodeQuestion, null=False, blank=False, on_delete=models.CASCADE)
    language = models.ForeignKey(Language, null=False, blank=False, on_delete=models.CASCADE)
    code = models.TextField(blank=True, null=True)


class TestCase(models.Model):
    """
    Two types of test cases: Sample and Internal
      - Sample: displayed to the user together with the problem description, has no score.
      - Internal: input/output are hidden by default, has score.
    """

    class Meta:
        pass

    code_question = models.ForeignKey(CodeQuestion, null=False, blank=False, on_delete=models.CASCADE)
    stdin = models.TextField(blank=False, null=False)
    stdout = models.TextField(blank=False, null=False)
    time_limit = models.PositiveIntegerField(default=5)
    memory_limit = models.PositiveIntegerField(default=40960)

    score = models.PositiveIntegerField()
    hidden = models.BooleanField(default=True)
    sample = models.BooleanField(default=False)


class CodeTemplate(models.Model):
    class Meta:
        pass

    language = models.ForeignKey(Language, null=False, blank=False, on_delete=models.CASCADE)
    name = models.CharField(max_length=50, blank=False, null=False)
    code = models.TextField(blank=False, null=False)

class HDLQuestionConfig(models.Model):
    QUESTION_TYPES = [
        (1, "Module Design"),
        (2, "Testbench Design"),
        (3, "Module and Testbench Design"),
    ]

    CONFIGURATION_OPTIONS = [
        (1, "Generate module code"),
    ]

    class Meta:
        pass

    def get_question_type(self):
        """
        Returns the question type of the HDL question.
        """
        return self.QUESTION_TYPES[self.question_type - 1][1]
    
    code_question = models.OneToOneField(CodeQuestion, null=True, blank=True, on_delete=models.CASCADE)
    question_type = models.IntegerField(choices=QUESTION_TYPES, default=1)
    question_config = models.IntegerField(choices=CONFIGURATION_OPTIONS, default=1)

class HDLQuestionSolution(models.Model):
    code_question = models.OneToOneField(CodeQuestion, null=True, blank=True, on_delete=models.CASCADE)
    module = models.TextField(blank=True, null=True)
    testbench = models.TextField(blank=True, null=True)