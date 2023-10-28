# Generated by Django 4.0.3 on 2022-09-29 10:24

from datetime import timedelta
from django.conf import settings
import django.contrib.auth.models
import django.contrib.auth.validators
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.CreateModel(
            name='User',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
                ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
                ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
                ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
                ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('first_name', models.CharField(max_length=150, verbose_name='first name')),
                ('last_name', models.CharField(max_length=150, verbose_name='last name')),
                ('session_key', models.CharField(blank=True, max_length=32, null=True)),
                ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
                ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),
            ],
            options={
                'permissions': (('can_create_student', 'Can create student accounts'), ('can_create_educator', 'Can create educator accounts'), ('can_create_lab_assistant', 'Can create lab assistant accounts')),
            },
            managers=[
                ('objects', django.contrib.auth.models.UserManager()),
            ],
        ),
        migrations.CreateModel(
            name='Language',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
                ('judge_language_id', models.IntegerField(unique=True)),
                ('ace_mode', models.CharField(max_length=50)),
                ('concurrency_support', models.BooleanField(default=False)),
            ],
        ),
        migrations.CreateModel(
            name='Assessment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('time_start', models.DateTimeField(blank=True, null=True)),
                ('time_end', models.DateTimeField(blank=True, null=True)),
                ('duration', models.PositiveIntegerField()),
                ('num_attempts', models.PositiveIntegerField()),
                ('instructions', models.TextField()),
                ('deleted', models.BooleanField(default=False)),
                ('show_grade', models.BooleanField(default=False)),
                ('published', models.BooleanField(default=False)),
                ('pin', models.PositiveIntegerField(blank=True, null=True)),
                ('weightage', models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='AssessmentAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('time_started', models.DateTimeField(auto_now_add=True)),
                ('time_submitted', models.DateTimeField(blank=True, null=True)),
                ('auto_submit', models.BooleanField(blank=True, null=True)),
                ('score', models.PositiveIntegerField(blank=True, null=True)),
                ('best_attempt', models.BooleanField(blank=True, null=True)),
                ('assessment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.assessment')),
                ('candidate', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='QuestionBank',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('description', models.TextField()),
                ('private', models.BooleanField(default=True)),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_qbs', to=settings.AUTH_USER_MODEL)),
                ('shared_with', models.ManyToManyField(blank=True, related_name='qbs_shared_with_me', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='CodeQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('description', models.TextField()),
                ('assessment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='core.assessment')),
                ('is_concurrency_question', models.BooleanField(default=False)),
                ('solution_code', models.TextField(blank=True, null=True)),
                ('solution_code_language', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.language')),
            ],
        ),
        migrations.CreateModel(
            name='CodeQuestionAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('assessment_attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.assessmentattempt')),
                ('code_question', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.codequestion')),
                ('time_spent', models.DurationField(default=timedelta(seconds=0))),
            ],
        ),
        migrations.CreateModel(
            name='CodeQuestionAttemptSnippet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.TextField()),
                ('language', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.language')),
                ('cq_attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.codequestionattempt')),
                ('updated_at', models.DateTimeField(auto_now=True))
            ],
        ),
        migrations.CreateModel(
            name='CodeQuestionSubmission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('time_submitted', models.DateTimeField(auto_now_add=True)),
                ('passed', models.BooleanField(blank=True, null=True)),
                ('code', models.TextField()),
                ('cq_attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.codequestionattempt')),
            ],
        ),
        migrations.CreateModel(
            name='Course',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('code', models.CharField(max_length=20)),
                ('year', models.PositiveIntegerField(validators=[django.core.validators.MaxValueValidator(9999)])),
                ('semester', models.CharField(choices=[('1', 'SEMESTER 1'), ('2', 'SEMESTER 2'), ('0', 'SPECIAL TERM')], default='1', max_length=1)),
                ('active', models.BooleanField(default=True)),
                ('maintainers', models.ManyToManyField(blank=True, related_name='maintained_courses', to=settings.AUTH_USER_MODEL)),
                ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'permissions': (('can_add_students', 'Can add students to the course'), ('can_remove_students', 'Can remove students from the course')),
            },
        ),
        migrations.CreateModel(
            name='Tag',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True)),
            ],
        ),
        migrations.CreateModel(
            name='TestCase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stdin', models.TextField()),
                ('stdout', models.TextField()),
                ('time_limit', models.PositiveIntegerField(default=5)),
                ('memory_limit', models.PositiveIntegerField(default=40960)),
                ('score', models.PositiveIntegerField()),
                ('hidden', models.BooleanField(default=True)),
                ('sample', models.BooleanField(default=False)),
                ('code_question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.codequestion')),
            ],
        ),
        migrations.CreateModel(
            name='TestCaseAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.CharField(max_length=36)),
                ('status', models.IntegerField(choices=[(1, 'In Queue'), (2, 'Processing'), (3, 'Accepted'), (4, 'Wrong Answer'), (5, 'Time Limit Exceeded'), (6, 'Compilation Error'), (7, 'Runtime Error (SIGSEGV)'), (8, 'Runtime Error (SIGXFSZ)'), (9, 'Runtime Error (SIGFPE)'), (10, 'Runtime Error (SIGABRT)'), (11, 'Runtime Error (NZEC)'), (12, 'Runtime Error (Other)'), (13, 'Internal Error'), (14, 'Exec Format Error')], default=1)),
                ('stdout', models.TextField(blank=True, null=True)),
                ('time', models.FloatField(blank=True, null=True)),
                ('memory', models.FloatField(blank=True, null=True)),
                ('cq_submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.codequestionsubmission')),
                ('test_case', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.testcase')),
            ],
        ),
        migrations.CreateModel(
            name='CourseGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=20)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.RESTRICT, to='core.course')),
                ('students', models.ManyToManyField(blank=True, related_name='enrolled_groups', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='CodeTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('code', models.TextField()),
                ('language', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.language')),
            ],
        ),
        migrations.CreateModel(
            name='CodeSnippet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.TextField(blank=True, null=True)),
                ('code_question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.codequestion')),
                ('language', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.language')),
            ],
        ),
        migrations.CreateModel(
            name='McqQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('description', models.TextField()),
                ('tags', models.ManyToManyField(blank=True, to='core.tag')),
                ('score', models.PositiveIntegerField(blank=False, null=False)),
                ('multiple_answers', models.BooleanField(default=False)),
                ('assessment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='core.assessment')),
                ('question_bank', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.questionbank')),
            ],
        ),
        migrations.CreateModel(
            name='McqQuestionOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mcq_question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.mcqquestion')),
                ('content', models.CharField(max_length=100)),
                ('correct', models.BooleanField(default=False, blank=False, null=False)),
            ],
        ),
        migrations.CreateModel(
            name='McqQuestionAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('assessment_attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.assessmentattempt')),
                ('mcq_question', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.mcqquestion')),
                ('time_spent', models.DurationField(default=timedelta(seconds=0))),
            ],
        ),
        migrations.CreateModel(
            name='McqQuestionAttemptOption',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('time_submitted', models.DateTimeField(auto_now_add=True)),
                ('mcq_attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.mcqquestionattempt')),
                ('selected_option', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.mcqquestionoption')),
            ],
        ),
        migrations.AddField(
            model_name='codequestionsubmission',
            name='language',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.language'),
        ),
        migrations.AddField(
            model_name='codequestion',
            name='question_bank',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.questionbank'),
        ),
        migrations.AddField(
            model_name='codequestion',
            name='tags',
            field=models.ManyToManyField(blank=True, to='core.tag'),
        ),
        migrations.AddField(
            model_name='assessment',
            name='course',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='core.course'),
        ),
    ]
