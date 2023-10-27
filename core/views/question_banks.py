from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db import transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.text import slugify
from rest_framework.exceptions import ParseError, PermissionDenied
from rest_framework.parsers import JSONParser
from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view, renderer_classes
from rest_framework.renderers import JSONRenderer

from core.decorators import UserGroup, groups_allowed
from core.forms.question_banks import QuestionBankForm, ImportQuestionBankForm
from core.models import QuestionBank, User, CodeQuestion, McqQuestion
from core.serializers import QuestionBankSerializer
from core.views.utils import check_permissions_qb, check_permissions_question


@login_required()
@groups_allowed(UserGroup.educator)
def view_question_banks(request):
    # all question banks (public/private) owned by the current user
    owned_question_banks = QuestionBank.objects.filter(owner=request.user)

    # private question banks that were shared with the current user
    shared_question_banks = QuestionBank.objects.filter(shared_with=request.user, private=True)

    # all public question banks regardless of ownership
    public_question_banks = QuestionBank.objects.filter(private=False)

    context = {
        'owned_qbs': owned_question_banks,
        'shared_qbs': shared_question_banks,
        'public_qbs': public_question_banks,
    }

    return render(request, 'question_banks/question_banks.html', context)


@login_required()
@groups_allowed(UserGroup.educator)
def create_question_bank(request):
    # initialize form
    form = QuestionBankForm()

    # process POST request
    if request.method == "POST":
        form = QuestionBankForm(request.POST)
        if form.is_valid():
            created_qb = form.save(commit=False)
            created_qb.owner = request.user
            created_qb.save()
            messages.success(request, "The question bank has been created! ✅")
            return redirect('view-question-banks')

    context = {
        'form': form
    }

    return render(request, 'question_banks/create-question-bank.html', context)


@login_required()
@groups_allowed(UserGroup.educator)
def update_question_bank(request, question_bank_id):
    # get question bank object
    question_bank = get_object_or_404(QuestionBank.objects.prefetch_related('owner'), id=question_bank_id)

    # check permissions of question bank
    if check_permissions_qb(question_bank, request.user) != 2:
        raise PermissionDenied("You do not have permissions to modify the question bank.")

    # initialize form with question bank instance
    form = QuestionBankForm(instance=question_bank)

    # process POST request
    if request.method == "POST":
        form = QuestionBankForm(request.POST, instance=question_bank)

        if form.is_valid():
            form.save()
            messages.success(request, "The question bank has been updated! ✅")

            # redirect to where the user came from
            next_url = request.GET.get("next")
            if next_url:
                return HttpResponseRedirect(next_url)
            else:
                return redirect('view-question-banks')

    context = {
        'question_bank': question_bank,
        'form': form,
    }

    return render(request, 'question_banks/update-question-bank.html', context)


@login_required()
@groups_allowed(UserGroup.educator)
def question_bank_details(request, question_bank_id):
    # get question bank object
    question_bank = get_object_or_404(QuestionBank.objects.prefetch_related('owner', 'shared_with', 'codequestion_set', 'codequestion_set__testcase_set', 'mcqquestion_set'), id=question_bank_id)

    # if no permissions, redirect back to course page
    if check_permissions_qb(question_bank, request.user) == 0:
        raise PermissionDenied("You do not have permissions to view the question bank.")

    # get a list of staff accounts (educator and superusers)
    staff = User.objects.filter(Q(groups__name__in=('educator',)) & ~Q(username=request.user.username))

    context = {
        'question_bank': question_bank,
        'staff': staff,
    }

    return render(request, 'question_banks/question-bank-details.html', context)


@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator)
def update_qb_shared_with(request):
    """
    Function to share/unshare a question bank with a user.
    Front-end does not display error messages for this feature, thus only the result of the operation is returned.
    """
    try:
        if request.method == "POST":
            # default error response
            error_context = { "result": "error", }

            # get params
            question_bank_id = request.POST.get("question_bank_id")
            user_id = request.POST.get("user_id")
            action = request.POST.get("action")

            # missing params
            if question_bank_id is None or user_id is None or action is None:
                return Response(error_context, status=status.HTTP_400_BAD_REQUEST)

            # get question bank object
            question_bank = QuestionBank.objects.filter(id=question_bank_id).prefetch_related('owner',
                                                                                            'shared_with').first()

            # question bank not found
            if not question_bank:
                return Response(error_context, status=status.HTTP_404_NOT_FOUND)

            # check if user has permissions for this question bank
            if check_permissions_qb(question_bank, request.user) != 2:
                return Response(error_context, status=status.HTTP_401_UNAUTHORIZED)

            # get user object
            user = User.objects.filter(id=user_id).first()

            # if user not found
            if not user:
                return Response(error_context, status=status.HTTP_404_NOT_FOUND)

            # add user to question bank
            if action == "add":
                question_bank.shared_with.add(user)
            elif action == "remove":
                question_bank.shared_with.remove(user)
            else:
                return Response(error_context, status=status.HTTP_400_BAD_REQUEST)

            # return success
            return Response({ "result": "success" }, status=status.HTTP_200_OK)

    except Exception as ex:
        error_context = { 
            "result": "error",
            "message": f"{ex}"
        }
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@renderer_classes([JSONRenderer])
@login_required()
@groups_allowed(UserGroup.educator)
def delete_question(request):
    """
    Deletes a Question from either a QuestionBank or an Assessment.
    Question can be CodeQuestion or McqQuestion.
    """
    try:
        if request.method == "POST":
            # generic error response
            error_context = { "result": "error", }

            # get params
            question_id = request.POST.get("question_id")
            question_type = request.POST.get("question_type")

            # missing params
            if question_id is None:
                return Response(error_context, status=status.HTTP_400_BAD_REQUEST)

            # get CodeQuestion object
            if question_type == "code":
                question = CodeQuestion.objects.filter(id=question_id).first()
            elif question_type == "mcq":
                question = McqQuestion.objects.filter(id=question_id).first()

            # check permissions
            if check_permissions_question(question, request.user) != 2:
                return Response(error_context, status=status.HTTP_401_UNAUTHORIZED)

            # if it belongs to an assessment, disallow if assessment has already been published
            if question.assessment and question.assessment.published:
                return Response(error_context, status=status.HTTP_403_FORBIDDEN)

            with transaction.atomic():
                # remove past attempts
                if question.assessment:
                    question.assessment.assessmentattempt_set.all().delete()

                # delete code question
                question.delete()

            return Response({ "result": "success" }, status=status.HTTP_200_OK)

    except Exception as ex:
        error_context = { 
            "result": "error",
            "message": f"{ex}"
        }
        return Response(error_context, status=status.HTTP_400_BAD_REQUEST)
    

@login_required()
@groups_allowed(UserGroup.educator)
def export_question_bank(request, question_bank_id):
    question_bank = get_object_or_404(QuestionBank, id=question_bank_id)

    # check permissions
    if check_permissions_qb(question_bank, request.user) == 0:
        raise PermissionDenied("You do not have permissions to export the question bank.")

    serialized = QuestionBankSerializer(question_bank)
    response = JsonResponse(serialized.data)
    response['Content-Disposition'] = f'attachment; filename={slugify(question_bank.name)}.json'
    return response


@login_required()
@groups_allowed(UserGroup.educator)
def import_question_bank(request):
    form = ImportQuestionBankForm()

    if request.method == "POST":
        form = ImportQuestionBankForm(request.POST, request.FILES)

        if form.is_valid():
            # retrieve the file
            file = request.FILES['file']

            # process the file
            try:
                # parse file as json
                data = JSONParser().parse(file)

                # pass it into serializer
                serializer = QuestionBankSerializer(data=data)

                # validate
                if serializer.is_valid():
                    # save to database, set the current user as the owner
                    question_bank = serializer.save(owner=User.objects.get(username=request.user))

                    # redirect to the created question bank
                    messages.success(request, "Question Bank imported successfully!")
                    return redirect('question-bank-details', question_bank_id=question_bank.id)
                else:
                    messages.warning(request, "Import failed, invalid json file.")

            except ParseError:
                messages.warning(request, "Import failed, source file was not in a valid json format.")
            except Exception as e:
                messages.warning(request, "Import failed, something went wrong.")

    context = {
        'form': form
    }

    return render(request, 'question_banks/import-question-bank.html', context)


@login_required()
@groups_allowed(UserGroup.educator)
def delete_question_bank(request, question_bank_id):
    if request.method == "POST":
        # get question bank
        question_bank = get_object_or_404(QuestionBank, id=question_bank_id)

        # check permissions (only owner can delete)
        if check_permissions_qb(question_bank, request.user) != 2:
            messages.warning(request, "You do not have permissions to delete the question bank.")
        else:
            question_bank.delete()
            messages.success(request, "Question bank successfully deleted!")

        return redirect('view-question-banks')
