from django.urls import include, path, re_path
from django.views.static import serve
from django.conf import settings

from .views import auth, user_management, dashboards, course_management, question_banks, code_questions, assessments, attempts, reports, mcq_questions

static_urlpatterns = [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
    re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
]

urlpatterns = [
    # static files
    path("", include(static_urlpatterns)),

    # global auth
    path('login/', auth.Login.as_view(), name='login'),
    path('logout/', auth.Logout.as_view(), name='logout'),
    path('change-password/', auth.change_password, name='change-password'),

    # dashboards
    path('dashboard/students/', dashboards.dashboard_students, name='dashboard-students'),
    path('dashboard/educators/', dashboards.dashboard_educators, name='dashboard-educators'),
    path('dashboard/lab-assistants/', dashboards.dashboard_lab_assistants, name='dashboard-lab-assistants'),
    path('dashboard/', dashboards.dashboard, name='dashboard'),
    path('', dashboards.dashboard, name='dashboard'),

    # create student
    path('enrol-students/', user_management.enrol_students, name='enrol-students'),
    path('api/enrol-students-bulk/', user_management.enrol_students_bulk, name='enrol-students-bulk'),  # ajax

    # course management
    path('courses/', course_management.view_courses, name='view-courses'),
    path('courses/create/', course_management.create_course, name='create-course'),
    path('courses/update/<int:course_id>/', course_management.update_course, name='update-course'),
    path('courses/details/<int:course_id>/', course_management.course_details, name='course-details'),
    path('api/remove-student-from-course/', course_management.remove_student, name='remove-student-from-course'),  # ajax
    path('api/update-course-maintainer/', course_management.update_course_maintainer, name='update-course-maintainer'),  # ajax
    path('api/reset-student-password/', course_management.reset_student_password, name='reset-student-password'),  # ajax

    # question banks
    path('qb/', question_banks.view_question_banks, name='view-question-banks'),
    path('qb/create/', question_banks.create_question_bank, name='create-question-bank'),
    path('qb/update/<int:question_bank_id>/', question_banks.update_question_bank, name='update-question-bank'),
    path('qb/details/<int:question_bank_id>/', question_banks.question_bank_details, name='question-bank-details'),
    path('api/update-qb-shared-with/', question_banks.update_qb_shared_with, name='update-qb-shared-with'),  # ajax
    path('api/delete-question/', question_banks.delete_question, name='delete-question'),  # ajax
    path('qb/export/<question_bank_id>/', question_banks.export_question_bank, name='export-question-bank'),
    path('qb/import/', question_banks.import_question_bank, name='import-question-bank'),
    path('qb/delete/<int:question_bank_id>/', question_banks.delete_question_bank, name='delete-question-bank'),

    # code questions
    path('code-question/create/<str:parent>/<int:parent_id>/', code_questions.create_code_question, name='create-code-question'),  # step 1
    path('code-question/<int:code_question_id>/update-languages/', code_questions.update_languages, name='update-languages'),  # step 2
    path('code-question/<int:code_question_id>/update-question-type/', code_questions.update_question_type, name='update-question-type'),  # step 2.1 (HDL)
    path('code-question/<int:code_question_id>/generate-module-code/', code_questions.generate_module_code, name='generate-module-code'),  # step 2.2 (HDL)
    path('code-question/<int:code_question_id>/update-test-cases/', code_questions.update_test_cases, name='update-test-cases'),  # step 3
    path('code-question/update/<int:code_question_id>/', code_questions.update_code_question, name='update-code-question'),
    path('api/get-code-question-details/', code_questions.get_cq_details, name='get-code-question-details'),  # ajax
    path('api/compile-code/', code_questions.compile_code, name='compile-code'),  # ajax
    path('code-question/preview/<int:code_question_id>/', code_questions.preview_question, name='preview-question'),  # step 1

    # mcq questions
    path('mcq-question/create/<str:parent>/<int:parent_id>/', mcq_questions.create_mcq_question, name='create-mcq-question'),  
    path('mcq-question/update/<int:mcq_question_id>/', mcq_questions.update_mcq_question, name='update-mcq-question'),
    path('api/get-mcq-question-details/', mcq_questions.get_mcq_details, name='get-mcq-question-details'),  # ajax

    # assessments
    path('assessments/', assessments.view_assessments, name='view-assessments'),
    path('assessment/create/', assessments.create_assessment, name='create-assessment'),
    path('assessment/update/<int:assessment_id>/', assessments.update_assessment, name='update-assessment'),
    path('assessment/details/<int:assessment_id>/', assessments.assessment_details, name='assessment-details'),
    path('api/add-code-question-to-assessment/', assessments.add_code_question_to_assessment, name='add-code-question-to-assessment'),
    path('api/get-code-questions-questions/', assessments.get_code_questions, name='get-code-questions'),  # ajax
    path('assessment/publish/<int:assessment_id>/', assessments.publish_assessment, name='publish-assessment'),
    path('assessment/delete/<int:assessment_id>/', assessments.delete_assessment, name='delete-assessment'),
    path('assessment/undo-delete/<int:assessment_id>/', assessments.undo_delete_assessment, name='undo-delete-assessment'),

    # taking assessments (attempts)
    path('assessment/landing/<int:assessment_id>/', attempts.assessment_landing, name='assessment-landing'),
    path('assessment/enter/<int:assessment_id>/', attempts.enter_assessment, name='enter-assessment'),
    path('attempt/<int:assessment_attempt_id>/question/<int:question_index>/', attempts.attempt_question, name='attempt-question'),
    path('assessment/submit/<int:assessment_attempt_id>/', attempts.submit_assessment, name='submit-assessment'),
    path('api/upload-snapshot/<int:assessment_attempt_id>/', attempts.upload_snapshot, name='upload-snapshot'), #ajax
    path('detect-faces', attempts.detect_faces_initial, name='detect-faces'),
    path('assessment/save-code-attempt-snippet/<int:code_question_attempt_id>/', attempts.save_code_attempt_snippet, name='save-code-attempt-snippet'),
    path('assessment/save-mcq-attempt-options/<int:mcq_question_attempt_id>/', attempts.save_mcq_attempt_options, name='save-mcq-attempt-options'),

    # code question attempts
    path('api/submit-single-test-case/<int:test_case_id>/<int:code_question_id>', attempts.submit_single_test_case, name='submit-single-test-case'),  # ajax
    path('api/get-tc-details/', attempts.get_tc_details, name='get-tc-details'),  # ajax
    path('api/code-question-submission/<int:code_question_attempt_id>/', attempts.code_question_submission, name='code-question-submission'),  # ajax
    path('api/get-cq-submission-status/', attempts.get_cq_submission_status, name='get-cq-submission-status'),  # ajax

    # reports
    path('course/report/<int:course_id>/', reports.course_report, name='course-report'),
    path('assessment/report/<int:assessment_id>/', reports.assessment_report, name='assessment-report'),
    path('assessment/report/<int:assessment_id>/question/<int:question_id>', reports.question_report, name='question-report'),
    path('api/get-candidate-attempts/<int:assessment_id>/', reports.get_candidate_attempts, name='get-candidate-attempts'),  # ajax
    path('assessment/attempt/details/', reports.assessment_attempt_details, name='assessment-attempt-details'),
    path('assessment/code-submission/details/<int:cqs_id>/', reports.code_submission_details, name='code-submission-details'),
    path('api/mcq-attempt-details/', reports.mcq_attempt_details, name='mcq-attempt-details'), # ajax
    path('assessment/export-assessment-results/<int:assessment_id>/', reports.export_assessment_results, name='export-assessment-results'),
    path('assessment/submission/candidate-snapshots/', reports.candidate_snapshots, name='candidate-snapshots'),

    # exporting stdin, stdout
    path('export/testcase/stdin/', reports.export_test_case_stdin, name="export-test-case-stdin"),  # stdin
    path('export/testcase/stdout/', reports.export_test_case_stdout, name="export-test-case-stdout"),  # expected output
    path('export/tca/<int:tca_id>/stdout/', reports.export_test_case_attempt_stdout, name="export-test-case-attempt-stdout"),

    # testbench generation
    path('testbench/generate/', code_questions.testbench_generation, name='testbench-generation'),   # ajax

    # waveform display
    path('vcdrom/', attempts.vcdrom, name='vcdrom'),
    path('api/wavedrom/vcd2wavedrom', attempts.wavedrom, name='vcd2wavedrom')
]
