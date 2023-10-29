import re
import zipfile
import base64
import os
import requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import formset_factory, inlineformset_factory
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, renderer_classes
from rest_framework.renderers import JSONRenderer

from core.decorators import groups_allowed, UserGroup
from core.forms.question_banks import CodeQuestionForm, ModuleGenerationForm, QuestionSolutionForm, QuestionTypeForm
from core.models import QuestionBank, Assessment, CodeQuestion
from core.models.questions import HDLQuestionConfig, TestCase, CodeSnippet, Language, Tag
from core.serializers import CodeQuestionsSerializer
from core.views.utils import TestbenchGenerator, check_permissions_course, check_permissions_question, embed_inout_module, embed_inout_testbench, generate_module


@login_required()
@groups_allowed(UserGroup.educator)
def create_code_question(request, parent, parent_id):
    """
    For creating a new code question.
    Parent is either a Question Bank or an Assessment.
    """
    question_bank = None
    assessment = None

    # get object instance and check permissions
    if parent == "qb":
        question_bank = get_object_or_404(QuestionBank, id=parent_id)

        # the user must be the question bank's owner
        if question_bank.owner != request.user:
            return PermissionDenied("You do not have permissions to modify this question bank.")

    elif parent == "as":
        assessment = get_object_or_404(Assessment, id=parent_id)

        # the user must have permissions to the course
        if check_permissions_course(assessment.course, request.user) == 0:
            return PermissionDenied("You do not have permissions to modify this assessment.")

    else:
        raise Http404()

    # create form
    form = CodeQuestionForm()

    if request.method == "GET":
        context = {
        'assessment': assessment,
        'question_bank': question_bank,
        'description_placeholder': """This editor supports **markdown**! And math equations too!

You can do this: $a \\ne 0$, and this:
$$x = {-b \pm \sqrt{b^2-4ac} \over 2a}$$

**Click preview!**""",
            'form': form,
        }
        return render(request, 'code_questions/create-code-question.html', context)
    elif request.method == "POST":
        form = CodeQuestionForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                # create tags
                tags = request.POST.get('tags')
                tags = [t.title() for t in tags.split(",")]
                if tags:
                    Tag.objects.bulk_create([Tag(name=t) for t in tags], ignore_conflicts=True)

                # save code question
                code_question = form.save()

                # add tags to code question
                tags = Tag.objects.filter(name__in=tags).values_list('id', flat=True)
                code_question.tags.add(*tags)

                messages.success(request, "The code question has been created, please proceed to select the languages!")
                return redirect('update-languages', code_question_id=code_question.id)


@login_required()
@groups_allowed(UserGroup.educator)
def update_code_question(request, code_question_id):
    # get code question object
    code_question = get_object_or_404(CodeQuestion, id=code_question_id)

    # check permissions
    if check_permissions_question(code_question, request.user) != 2:
        if code_question.question_bank:
            return PermissionDenied("You do not have permissions to modify this question bank.")
        else:
            return PermissionDenied("You do not have permissions to modify this assessment.")

    # prepare form
    form = CodeQuestionForm(instance=code_question)

    if request.method == "GET":
        context = {
            'creation': CodeSnippet.objects.filter(code_question=code_question).count() == 0,
            'code_question': code_question,
            'form': form,
        }
        return render(request, 'code_questions/update-code-question.html', context)
    elif request.method == "POST":
        form = CodeQuestionForm(request.POST, instance=code_question)

        if form.is_valid():
            with transaction.atomic():
                # create tags
                tags = request.POST.get('tags')
                tags = [t.title() for t in tags.split(",")]
                if tags:
                    Tag.objects.bulk_create([Tag(name=t) for t in tags], ignore_conflicts=True)

                code_question = form.save()
                messages.success(request, "Code Question successfully updated!")

                # clear old tags and add tags to code question
                code_question.tags.clear()
                tags = Tag.objects.filter(name__in=tags).values_list('id', flat=True)
                code_question.tags.add(*tags)

                if code_question.question_bank:
                    return redirect('question-bank-details', question_bank_id=code_question.question_bank.id)
                else:
                    return redirect('assessment-details', assessment_id=code_question.assessment.id)


@login_required()
@groups_allowed(UserGroup.educator)
def update_test_cases(request, code_question_id):
    # get CodeQuestion instance
    code_question = get_object_or_404(CodeQuestion, id=code_question_id)
    # get CodeSnippet instance
    code_snippets = CodeSnippet.objects.filter(code_question=code_question)

    # check permissions
    if check_permissions_question(code_question, request.user) != 2:
        return PermissionDenied()

    # if belongs to a published assessment, disallow
    if code_question.assessment and code_question.assessment.published:
        messages.warning(request, "Test cases from a published assessment cannot be modified!")
        return redirect('assessment-details', assessment_id=code_question.assessment.id)

    # prepare formset
    # Module and Testbench Design HDL questions have 2 test cases (Module and Testbench) for each test case
    extra_test_cases = 0
    if code_question.testcase_set.count() == 0: # new code question, create extra test cases
        if hasattr(code_question, 'hdlquestionconfig'):
            question_type = code_question.hdlquestionconfig.get_question_type()
            if question_type == 'Testbench Design':
                extra_test_cases = 1
            elif question_type == 'Module and Testbench Design':
                extra_test_cases = 6
            else:
                extra_test_cases = 3
        else:
            extra_test_cases = 3
    else:   # existing code question
        if hasattr(code_question, 'hdlquestionconfig') and code_question.hdlquestionconfig.get_question_type() == 'Module and Testbench Design':
            extra_test_cases = 0

    # Create the TestCaseFormset with the determined number of extra test cases
    TestCaseFormset = inlineformset_factory(
        CodeQuestion,
        TestCase,
        extra=extra_test_cases,
        fields=['stdin', 'stdout', 'time_limit', 'memory_limit', 'score', 'hidden', 'sample']
    )
    testcase_formset = TestCaseFormset(prefix='tc', instance=code_question)

    # get question type
    if hasattr(code_question, 'hdlquestionconfig'):
        question_type = code_question.hdlquestionconfig.get_question_type()
    else:
        question_type = None

    # prepare HDL solution form
    if not code_question.is_software_language():
        if hasattr(code_question, 'hdlquestionsolution'):
            hdl_solution_form = QuestionSolutionForm(instance=code_question.hdlquestionsolution)
        else:
            hdl_solution_form = QuestionSolutionForm()

        if request.session.get('module'):
            hdl_solution_form.initial['module'] = request.session.get('module')
            hdl_solution_form.initial['testbench'] = request.session.get('testbench')
            
            del request.session['module']
            del request.session['testbench']
    else:
        code_question_form = CodeQuestionForm(instance=code_question)

    # process POST requests
    if request.method == "POST":
        if not code_question.is_software_language():
            hdl_solution_form = QuestionSolutionForm(request.POST)

            if hdl_solution_form.is_valid():
                # check if existing config exists
                if hasattr(code_question, 'hdlquestionsolution'):
                    code_question.hdlquestionsolution.delete()
                    
                question_sol = hdl_solution_form.save(commit=False)
                question_sol.code_question = code_question
                question_sol.save()
        else:
            code_question_form = CodeQuestionForm(request.POST, instance=code_question)
            if code_question_form.is_valid():
                question_sol = code_question_form.save(commit=True)

        testcase_formset = TestCaseFormset(request.POST, instance=code_question, prefix='tc')

        if testcase_formset.is_valid():
            with transaction.atomic():
                # remove past attempts
                if code_question.assessment:
                    code_question.assessment.assessmentattempt_set.all().delete()

                testcase_formset.save()
                messages.success(request, "Test cases updated!")

                next_url = request.GET.get("next")
                if next_url:
                    return redirect(next_url)
                
                if code_question.question_bank:
                    return redirect('question-bank-details', question_bank_id=code_question.question_bank.id)
                else:
                    return redirect('assessment-details', assessment_id=code_question.assessment.id)
    context = {
        'creation': request.GET.get('next') is None,
        'code_question': code_question,
        'code_snippet': code_snippets,
        'testcase_formset': testcase_formset,
        'question_type': question_type,
        'is_software_language': code_question.is_software_language(),
        'code_question_form': code_question_form if code_question.is_software_language() else None,
        'hdl_solution_form': hdl_solution_form if not code_question.is_software_language() else None,
    }

    return render(request, 'code_questions/update-test-cases.html', context)


@login_required()
@groups_allowed(UserGroup.educator)
def update_languages(request, code_question_id):
    # get CodeQuestion instance
    code_question = get_object_or_404(CodeQuestion, id=code_question_id)

    # check permissions
    if check_permissions_question(code_question, request.user) != 2:
        return PermissionDenied()

    # if belongs to a published assessment, disallow
    if code_question.assessment and code_question.assessment.published:
        messages.warning(request, "Languages from a published assessment cannot be modified!")
        return redirect('assessment-details', assessment_id=code_question.assessment.id)

    # prepare formset
    CodeSnippetFormset = inlineformset_factory(CodeQuestion, CodeSnippet, extra=0, fields=['language', 'code'])
    code_snippet_formset = CodeSnippetFormset(prefix='cs', instance=code_question)

    # filter languages offered
    languages = Language.objects.filter(concurrency_support=True) if code_question.is_concurrency_question else Language.objects.all()

    if request.method == "GET":
        context = {
            'creation': request.GET.get('next') is None or CodeSnippet.objects.filter(code_question=code_question).count() == 0,
            'code_question': code_question,
            'code_snippet_formset': code_snippet_formset,
            'languages': languages,
            'existing_languages': code_question.codesnippet_set.all().values_list('language', flat=True).distinct()
        }

        return render(request, 'code_questions/update-languages.html', context)
    elif request.method == "POST":
        code_snippet_formset = CodeSnippetFormset(request.POST, instance=code_question, prefix='cs')

        if code_snippet_formset.is_valid():
            with transaction.atomic():
                # remove past attempts
                if code_question.assessment:
                    code_question.assessment.assessmentattempt_set.all().delete()

                cq_is_software = code_question.is_software_language()

                code_snippet_formset.save()
                messages.success(request, "Code Snippets saved!")

                name = ''

                # get first undeleted language
                for form in code_snippet_formset:
                    if form.cleaned_data.get('DELETE') is True:
                        continue
                    name = form.cleaned_data.get('language')
                    break
                
                # remove all test cases if language type is changed
                language = get_object_or_404(Language, name=name)
                if language.software_language != cq_is_software:
                    code_question.testcase_set.all().delete()
                    
                    if hasattr(code_question, 'hdlquestionconfig'):
                        code_question.hdlquestionconfig.delete()

                    if not language.software_language:
                        return redirect('update-question-type', code_question_id=code_question.id)

                    return redirect('update-test-cases', code_question_id=code_question.id)

                next_url = request.GET.get("next")
                if next_url:
                    return redirect(next_url)
                
                if code_question.is_software_language():
                    return redirect('update-test-cases', code_question_id=code_question.id)
                else:
                    return redirect('update-question-type', code_question_id=code_question.id)


@login_required()
@groups_allowed(UserGroup.educator)
def update_question_type(request, code_question_id):
    # get CodeQuestion instance
    code_question = get_object_or_404(CodeQuestion, id=code_question_id)

    # check permissions
    if check_permissions_question(code_question, request.user) != 2:
        return PermissionDenied()
    
    # if belongs to a published assessment, disallow
    if code_question.assessment and code_question.assessment.published:
        messages.warning(request, "Question type from a published assessment cannot be modified!")
        return redirect('assessment-details', assessment_id=code_question.assessment.id)
    
    # prepare form
    question_type_form = QuestionTypeForm()

    # process POST requests
    if request.method == "POST":
        form = QuestionTypeForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                # remove existing config
                if hasattr(code_question, 'hdlquestionconfig'):
                    code_question.hdlquestionconfig.delete()

                hdl_config = form.save(commit=False)
                hdl_config.code_question = code_question
                hdl_config.save()

                next_url = request.GET.get("next")
                if next_url:
                    return redirect(next_url)
                
                return redirect('generate-module-code', code_question_id=code_question.id)
    
    context = {
        'creation': request.GET.get('next') is None or HDLQuestionConfig.objects.filter(code_question=code_question).count() == 0,
        'code_question': code_question,
        'question_type_form': question_type_form,
    }

    return render(request, 'code_questions/update-question-type.html', context)

@login_required()
def generate_module_code(request, code_question_id):
    # get CodeQuestion instance
    code_question = get_object_or_404(CodeQuestion, id=code_question_id)

    # check permissions
    if check_permissions_question(code_question, request.user) != 2:
        return PermissionDenied()

    # if belongs to a published assessment, disallow
    if code_question.assessment and code_question.assessment.published:
        messages.warning(request, "Question type from a published assessment cannot be modified!")
        return redirect('assessment-details', assessment_id=code_question.assessment.id)
    
    # render form
    ModuleGenerationFormset = formset_factory(ModuleGenerationForm, extra=0)
    module_generation_formset = ModuleGenerationFormset(prefix='module', initial=[{'module_name': '', 'port_direction': 'input', 'bus': False, 'msb': 0, 'lsb': 0}])

    # process POST requests
    if request.method == "POST":
        # check if skip button is pressed
        if 'skip' in request.POST:
            return redirect('update-test-cases', code_question_id=code_question.id)
        
        module_generation_formset = ModuleGenerationFormset(request.POST, prefix='module')

        if module_generation_formset.is_valid():
            # Generate Verilog module code using the form inputs
            module_name = module_generation_formset[0].cleaned_data.get('module_name')

            ports = []
            for form in module_generation_formset:
                port_name = form.cleaned_data.get('port_name')
                port_direction = form.cleaned_data.get('port_direction')
                bus = form.cleaned_data.get('bus')
                msb = form.cleaned_data.get('msb')
                lsb = form.cleaned_data.get('lsb')
                ports.append({
                    'name': port_name,
                    'direction': port_direction,
                    'bus': bus,
                    'msb': msb,
                    'lsb': lsb,
                })

            module_code = generate_module(module_name, ports)
            testbench = TestbenchGenerator(module_code)()

            request.session['module'] = module_code
            request.session['testbench'] = testbench

            next_url = request.GET.get("next")
            if next_url:
                return redirect(next_url)

            return redirect('update-test-cases', code_question_id=code_question.id)

    context = {
        'creation': request.GET.get('next') is None,
        'code_question': code_question,
        'module_formset': module_generation_formset,
    }

    return render(request, 'code_questions/generate-module-code.html', context)

@api_view(["GET"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator, UserGroup.lab_assistant)
def get_cq_details(request):
    try:
        error_context = {"result": "error", }

        if request.method == "GET":
            # get cq_id from request
            cq_id = request.GET.get("cq_id")

            # get code question object
            code_question = CodeQuestion.objects.filter(id=cq_id).first()

            # code question not found
            if not code_question:
                return Response(error_context, status=status.HTTP_404_NOT_FOUND)

            # check permissions
            if check_permissions_question(code_question, request.user) == 0:
                return Response(error_context, status=status.HTTP_401_UNAUTHORIZED)

            # prepare context and serialize code question
            context = {
                "result": "success",
                "code_question": CodeQuestionsSerializer(code_question, many=False).data
            }

            return Response(context, status=status.HTTP_200_OK)

    except Exception as ex:
        context = { 
            "result": "error",
            "message": f"{ex}"
            }
        return Response(context, status=status.HTTP_400_BAD_REQUEST)
    
@api_view(["POST"])
@login_required()
@renderer_classes([JSONRenderer])
def testbench_generation(request):
    # get module_code from request
    module_code = request.POST.get("module_code")

    try:
        # generate testbench
        testbench = TestbenchGenerator(module_code)()

        context = {
            "result": "success",
            "testbench": testbench
        }

        return Response(context, status=status.HTTP_200_OK)
    
    except Exception as ex:
        context = { 
            "result": "error",
            "message": "Error in generating testbench. Please check that your module code has inputs and outputs defined."
        }
        return Response(context, status=status.HTTP_400_BAD_REQUEST)

@api_view(["POST"])
@login_required()
@groups_allowed(UserGroup.educator)
def compile_code(request):
    """
    Compiles the code snippet and returns the result.
    Used only for hardware language test case creation.
    Specify the output type in the request.
    """
    try:
        if request.method == "POST":
            language = Language.objects.get(judge_language_id=request.POST.get('lang-id'))
            module = request.POST.get('module')
            testbench = request.POST.get('testbench')
            
            if language.name.find('Verilog') != -1:
                if testbench.find('$dumpfile') == -1:
                    # add wave dump to last line before endmodule
                    testbench = testbench.replace('endmodule', 'initial begin $dumpfile("vcd_dump.vcd"); $dumpvars(0); end endmodule')
                else:
                    # Define the regular expression patterns
                    dumpfile_pattern = r'\$dumpfile\("[^"]+"\)'
                    dumpvars_pattern = r'\$dumpvars\(\d+\)'

                    # Replacement strings
                    new_dumpfile = '$dumpfile("vcd_dump.vcd")'
                    new_dumpvars = '$dumpvars(0)'

                    # replace wave dump
                    testbench = re.sub(dumpfile_pattern, new_dumpfile, testbench)
                    testbench = re.sub(dumpvars_pattern, new_dumpvars, testbench)
                try:
                    module, input_ports, output_ports = embed_inout_module(module)
                    testbench = embed_inout_testbench(testbench, input_ports, output_ports)
                except Exception as ex:
                    pass
            
            # create zip file
            with zipfile.ZipFile('submission.zip', 'w') as zip_file:
                zip_file.writestr('main.v', module)
                zip_file.writestr('testbench.v', testbench)
                zip_file.writestr('compile', 'iverilog -o a.out main.v testbench.v')
                zip_file.writestr('run', "vvp -n a.out | find -name '*.vcd' -exec python3 -m vcd2wavedrom.vcd2wavedrom --aasp -i {} + | tr -d '[:space:]'")

            # encode zip file
            with open('submission.zip', 'rb') as f:
                encoded = base64.b64encode(f.read()).decode('utf-8')

            # judge0 params
            params = {
                "additional_files": encoded,
                "language_id": request.POST.get('lang-id'),
            }
            
            # call judge0
            try:
                url = settings.JUDGE0_URL + "/submissions/?base64_encoded=false&wait=false"
                res = requests.post(url, json=params)
                data = res.json()
            except requests.exceptions.ConnectionError:
                error_context = {
                    "result": "error",
                    "message": "Judge0 API seems to be down.",
                }
                return Response(error_context, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            # return error if no token
            token = data.get("token")
            if not token:
                error_context = {
                    "result": "error",
                    "message": "Judge0 error.",
                }
                return Response(error_context, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            context = {
                "result": "success",
                "token": token,
            }
            return Response(context, status=status.HTTP_200_OK)
    
    except Exception as ex:
        error_context = {
            "result": "error",
            "message": f"{ex}",
        } 
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)
    
    finally:
        # delete zip file
        if os.path.exists('submission.zip'):
            os.remove('submission.zip')

@api_view(["GET"])
@login_required()
@groups_allowed(UserGroup.educator)
def preview_question(request, question_id):
    # get code question
    code_question = get_object_or_404(CodeQuestion, id=question_id)

    # if no question exist at the index, raise 404
    if not code_question:
        raise Http404()

    code_snippets = CodeSnippet.objects.filter(code_question=code_question)
    sample_tc = TestCase.objects.filter(code_question=code_question, sample=True).first()
    hidden_tc_stdin = list(TestCase.objects.filter(code_question=code_question, sample=False).values_list('stdin', flat=True))

    # context
    context = {
        'code_question': code_question,
        'code_snippets': code_snippets,
        'sample_tc': sample_tc,
        'hidden_tc_stdin': hidden_tc_stdin,
        'is_software_language': code_question.is_software_language(),
    }

    return render(request, "code_questions/preview-question.html", context)