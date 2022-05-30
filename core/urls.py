from django.urls import path

from .views import auth, user_management, dashboards, course_management, question_banks

urlpatterns = [
    # global auth
    path('login/', auth.Login.as_view(), name='login'),
    path('logout/', auth.Logout.as_view(), name='logout'),

    # dashboards
    path('dashboard/students/', dashboards.dashboard_students, name='dashboard-students'),
    path('dashboard/educators/', dashboards.dashboard_educators, name='dashboard-educators'),
    path('dashboard/labassistants/', dashboards.dashboard_lab_assistants, name='dashboard-lab-assistants'),
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
    path('api/add-students-to-course/', course_management.add_students, name='add-students-to-course'),  # ajax
    path('api/get-course-students/', course_management.get_course_students, name='get-course-students'),  # ajax
    path('api/update-course-maintainer/', course_management.update_course_maintainer, name='update-course-maintainer'),  # ajax

    # question banks
    path('qb/', question_banks.view_question_banks, name='view-question-banks'),
    path('qb/create/', question_banks.create_question_bank, name='create-question-bank'),



]
