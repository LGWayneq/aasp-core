# celery tasks
import requests
import cv2
import os
from celery import shared_task
from insightface.app import FaceAnalysis
from django.conf import settings
from django.core import mail
from django.utils import timezone

from core.models import TestCaseAttempt, CodeQuestionSubmission, AssessmentAttempt, CandidateSnapshot

@shared_task
def update_test_case_attempt_status(tca_id: int, token: str):
    """
    Polls judge0 to get the status_id of a single submission (one test case)
    If status_id has been changed, save the change to db.
    If the submission is still being processed, re-queue this task to be polled again later.
    """
    try:
        # call judge0
        url = f"{settings.JUDGE0_URL}/submissions/{token}?base64_encoded=false&fields=status_id,stdout,time,memory"
        res = requests.get(url)
        data = res.json()

        status_id = data.get('status_id')
        stdout = data.get('stdout')
        time = data.get('time')
        memory = data.get('memory')

        if status_id not in [1, 2]:
            tca = TestCaseAttempt.objects.prefetch_related('cq_submission').get(id=tca_id)
            tca.status = status_id
            tca.stdout = stdout
            tca.time = time
            tca.memory = memory
            tca.save()
            # check if all test cases have been completed
            finished = not TestCaseAttempt.objects.filter(cq_submission_id=tca.cq_submission.id, status__in=[1, 2]).exists()

            # only continue if test cases are complete
            if finished:
                update_cqs_passed_flag.delay(tca.cq_submission.id)
    except ConnectionError as e:
        print(e.message)


@shared_task
def update_cqs_passed_flag(cqs_id):
    """
    Checks if all test cases of a CodeQuestionSubmission has been processed by judge0.
    Update the "passed" field of the CQS instance and initiates the computation of the submission score.
    If it was already calculated previously, nothing will be done.
    """
    # # check if all test cases have been completed
    # finished = not TestCaseAttempt.objects.filter(cq_submission_id=cqs_id, status__in=[1, 2]).exists()

    # # only continue if test cases are complete
    # if finished:
    # get cqs object
    cqs = CodeQuestionSubmission.objects.get(id=cqs_id)

    # only continue if it was not previously calculated
    if cqs.passed is None:
        # update the passed flag
        passed = not TestCaseAttempt.objects.filter(cq_submission_id=cqs_id, status__range=(4, 14)).exists()
        cqs.passed = passed
        cqs.save()


@shared_task
def force_submit_assessment(assessment_attempt_id):
    """
    Server-side submission of an assessment.
    This ensures that an AssessmentAttempt will be marked as submitted when the duration runs out, even if the user is not on the
    assessment page.
    If the AssessmentAttempt was already submitted previously (i.e. by the user), nothing will be done.
    """
    try:
        assessment_attempt = AssessmentAttempt.objects.get(id=assessment_attempt_id, time_submitted=None)
        if assessment_attempt:
            assessment_attempt.auto_submit = True  # set the auto_submit flag
            assessment_attempt.time_submitted = timezone.now()
            assessment_attempt.save()
            # queue task to compute score for this AssessmentAttempt
            compute_assessment_attempt_score.apply_async((assessment_attempt.id,), countdown=1)
    except:
        pass


@shared_task
def compute_assessment_attempt_score(assessment_attempt_id):
    """
    This task is queued when an AssessmentAttempt has been submitted (both user-initiated and server-side)
    This tasks calculates the total score of the AssessmentAttempt, and determines if it is the best attempt.
    If the AssessmentAttempt contains a submission that is still being processed, the task will be delayed.
    """
    try:
        # get the instance
        assessment_attempt = AssessmentAttempt.objects.get(id=assessment_attempt_id)
        
        # if all test cases are complete, proceed to compute score
        if not assessment_attempt.has_processing_submission():
            assessment_attempt.compute_score()
        # if still processing, queue it again with a 5s delay
        else:
            compute_assessment_attempt_score.apply_async((assessment_attempt_id,), countdown=5)
    except:
        pass


@shared_task
def detect_faces(snapshot_id):
    """
    This task is queued when candidate snapshot is uploaded.
    This task uses InsightFace to detect number of faces in the snapshot.
    Celery worker will take some time to download model_pack_name on the first run, progress be viewed
    in the celery container logs.
    """
    try:
        snapshot = CandidateSnapshot.objects.get(id=snapshot_id)
        image_path = os.path.join(settings.MEDIA_ROOT, snapshot.image.name)

        model_pack_name = "buffalo_sc"
        app = FaceAnalysis(name=model_pack_name)
        app.prepare(ctx_id=0, det_size=(640, 640))
        image = cv2.imread(image_path)
        faces = app.get(image)

        snapshot.faces_detected = len(faces)
        snapshot.save()

    except:
        pass


@shared_task
def send_password_email(email, full_name, random_password, reset_password=False):
    """
    This task sends an email to student(s) their randomised initial/reset password.
    """
    try:
        subject = "Your Reset Password for AASP" if reset_password else "Your New Password for AASP"
        text_content = f"Dear {full_name},\n\nYour password is: {random_password}\nYou may change your password here. {settings.AASP_URL}/change-password/\n\n\n\
                        This is an automated message. Please do not reply."
        html_content = f"Dear {full_name},\
                        <br/><br/>\
                        <p>Your password is: {random_password}</p>\
                        <p>You may change your password <a href='{settings.AASP_URL}/change-password/'>here</a>.</p>\
                        <br/>\
                        <p><small>This is an automated message. Please do not reply.</small></p>"
        
        mail.send_mail(subject, text_content, settings.EMAIL_HOST_USER, [email], fail_silently=False, html_message=html_content)
    except:
        raise EmailException()


@shared_task
def send_assessment_published_email(id, name, course, start, end, duration, recipients):
    """
    This task sends a notification email to student(s) the URL of the assessment when it is published.

    Parameters:
    -----------
    id : int
        assessment id
    name : str
        assessment name
    course : str
        assessment course name
    recipients : list<dict> 
        "email" and "name" of recipients
    """
    try:
        datetime = '-' if start == None and end == None else f"{start} to {end}"
        start = '-' if start == None else start
        end = '-' if end == None else end
        
        duration = "Unlimited" if duration == 0 else f"{duration} min"
        
        subject = f"{course} {name} on AASP"
        for student in recipients:
            text_content = f"Dear {student['name']},\n\n\
                            Test Name: {name}\n\
                            Course: {course}\n\
                            Date/Time: {datetime}\n\
                            Duration: {duration}\n\
                            You may view details of the assessment here. {settings.AASP_URL}/assessment/landing/{id}/\n\n\n\
                            This is an automated message. Please do not reply."
            html_content = f"Dear {student['name']},\
                            <br/><br/>\
                            <p>Test Name: {name}</p>\
                            <p>Course: {course}</p>\
                            <p>Date/Time: {datetime}</p>\
                            <p>Duration: {duration}</p>\
                            <p>You may view details of the assessment <a href='{settings.AASP_URL}/assessment/landing/{id}/'>here</a>.</p>\
                            <br/>\
                            <p><small>This is an automated message. Please do not reply.</small></p>"
            
            mail.send_mail(subject, text_content, settings.EMAIL_HOST_USER, [student['email']], fail_silently=False, html_message=html_content)
    except:
        raise EmailException()


class EmailException(Exception):
    def __str__(self):
        return f"An error occurred. Please try again."