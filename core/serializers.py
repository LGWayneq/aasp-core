from django.db import transaction
from rest_framework import serializers

from core.models import CodeQuestion, Tag, TestCase, Language, QuestionBank, CodeSnippet, McqQuestion, McqQuestionOption


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['name']
        extra_kwargs = {
            'name': {'validators': []},
        }


class TestCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestCase
        fields = ['id', 'time_limit', 'memory_limit', 'score']


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = ['name']


class CodeQuestionsSerializer(serializers.ModelSerializer):
    tags = TagSerializer(read_only=True, many=True)
    testcase_set = TestCaseSerializer(read_only=True, many=True)
    languages = LanguageSerializer(read_only=True, many=True)

    class Meta:
        model = CodeQuestion
        fields = ['id', 'name', 'description', 'tags', 'question_bank', 'assessment', 'testcase_set', 'languages', 'is_concurrency_question', 'solution_code', 'solution_code_language']


class McqQuestionOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = McqQuestionOption
        fields = ['id', 'content', 'correct']


class McqQuestionSerializer(serializers.ModelSerializer):
    tags = TagSerializer(read_only=True, many=True)
    options_set = McqQuestionOptionSerializer(read_only=True, many=True)

    class Meta:
        model = McqQuestion
        fields = ['id', 'name', 'score', 'description', 'tags', 'question_bank', 'assessment', 'options_set', 'multiple_answers']


class TestCaseSerializerLite(serializers.ModelSerializer):
    """
    For importing/exporting question banks.
    Serializer for TestCase objects
    """

    class Meta:
        model = TestCase
        fields = ['stdin', 'stdout', 'time_limit', 'memory_limit', 'score', 'hidden', 'sample']


class LanguageSerializerLite(serializers.ModelSerializer):
    """
    For importing/exporting question banks.
    Serializer for Language objects
    """

    class Meta:
        model = Language
        fields = ['name', 'judge_language_id', 'ace_mode']
        extra_kwargs = {
            'name': {'validators': []},
            'judge_language_id': {'validators': []},
        }


class CodeSnippetSerializerLite(serializers.ModelSerializer):
    """
    For importing/exporting question banks.
    Serializer for CodeSnippet objects
    """
    language = LanguageSerializerLite()

    class Meta:
        model = CodeSnippet
        fields = ['language', 'code']


class CodeQuestionSerializerLite(serializers.ModelSerializer):
    """
    For importing/exporting question banks.
    Serializer for CodeQuestion objects
    """
    tags = TagSerializer(many=True)
    testcase_set = TestCaseSerializerLite(many=True)
    codesnippet_set = CodeSnippetSerializerLite(many=True)

    class Meta:
        model = CodeQuestion
        fields = ['name', 'description', 'tags', 'testcase_set', 'codesnippet_set']


class QuestionBankSerializer(serializers.ModelSerializer):
    """
    QuestionBank Serializer for importing/exporting question banks and its questions.
    """
    codequestion_set = CodeQuestionSerializerLite(many=True)

    class Meta:
        model = QuestionBank
        fields = ['name', 'description', 'codequestion_set']

    def create(self, validated_data):
        # wrap in atomic block to roll back transactions if an operation here fails
        with transaction.atomic():
            # create question bank
            question_bank = QuestionBank.objects.create(name=validated_data['name'],
                                                        description=validated_data['description'],
                                                        owner=validated_data['owner'])

            # for each code question:
            for cq in validated_data['codequestion_set']:
                # create code questions (tags may not exist)
                code_question = CodeQuestion.objects.create(name=cq['name'],
                                                            description=cq['description'],
                                                            question_bank=question_bank)

                # get tags
                tags = set([t['name'].title() for t in cq['tags']])

                # get tags that already exist (so that we don't create them again)
                existing_tags = set(Tag.objects.filter(name__in=tags).values_list('name', flat=True))

                # create the new tags
                new_tags = tags - existing_tags
                new_tags = [Tag(name=t) for t in new_tags]
                Tag.objects.bulk_create(new_tags)

                # add tags to code question
                tags = Tag.objects.filter(name__in=tags).values_list('id', flat=True)
                code_question.tags.add(*tags)

                # create test case
                for tc in cq['testcase_set']:
                    test_case = TestCase.objects.create(code_question=code_question, **tc)

                # create code snippet (lang may not exist)
                for cs in cq['codesnippet_set']:
                    # create code snippet
                    code_snippet = CodeSnippet.objects.create(code_question=code_question,
                                                              language=Language.objects.get_or_create(**cs['language'])[0],
                                                              code=cs['code'])

                return code_question
