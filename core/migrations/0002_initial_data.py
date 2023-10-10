# Data Migration file for populating the initial database with REQUIRED data

from django.contrib.auth.hashers import make_password
from django.db import migrations


class Migration(migrations.Migration):

    # default groups
    def create_groups(apps, schema_editor):
        Group = apps.get_model('auth', 'Group')
        Group.objects.bulk_create([
            Group(name='educator'),
            Group(name='lab_assistant'),
            Group(name='student'),
        ])

    # default admin account
    def create_admin(apps, schema_editor):
        User = apps.get_model('core', 'User')
        User.objects.create(
            username="ADMIN",
            email='ADMIN@EXAMPLE.COM',
            password=make_password('password123'),
            is_staff=True,
            is_superuser=True,
        )

    def create_users(apps, schema_editor):
        Group = apps.get_model('auth', 'Group')
        User = apps.get_model('core', 'User')

        User.objects.create(
            username="YRLOKE",
            first_name="YUAN REN",
            last_name="LOKE",
            email='YRLOKE@NTU.EDU.SG',
            password=make_password('password123'),
            is_staff=False,
            is_superuser=False,
        )
        User.objects.create(
            username="JLEE254",
            first_name="JUN WEI",
            last_name="LEE",
            email='JLEE254@E.NTU.EDU.SG',
            password=make_password('password123'),
            is_staff=False,
            is_superuser=False,
        )
        User.objects.create(
            username="LIM287",
            first_name="JASMINE",
            last_name="LIM",
            email='LIM287@NTU.EDU.SG',
            password=make_password('password123'),
            is_staff=False,
            is_superuser=False,
        )
        User.objects.create(
            username="WLIU020",
            first_name="WING LAM",
            last_name="LIU",
            email='WLIU020@E.NTU.EDU.SG',
            password=make_password('password123'),
            is_staff=False,
            is_superuser=False,
        )
        User.objects.create(
            username="CHUA0994",
            first_name="CHONG YIH",
            last_name="CHUA",
            email='CHUA0994@E.NTU.EDU.SG',
            password=make_password('password123'),
            is_staff=False,
            is_superuser=False,
        )
        User.objects.create(
            username="GLIAU001",
            first_name="G WAYNE",
            last_name="LIAU",
            email='GLIAU001@E.NTU.EDU.SG',
            password=make_password('password123'),
            is_staff=False,
            is_superuser=False,
        )
        Group.objects.get(name="educator").user_set.add(User.objects.get(username='YRLOKE'))
        Group.objects.get(name="student").user_set.add(User.objects.get(username='JLEE254'))
        Group.objects.get(name="student").user_set.add(User.objects.get(username='WLIU020'))
        Group.objects.get(name="student").user_set.add(User.objects.get(username='CHUA0994'))
        Group.objects.get(name="student").user_set.add(User.objects.get(username='GLIAU001'))
        Group.objects.get(name="lab_assistant").user_set.add(User.objects.get(username='LIM287'))

    # default languages and corresponding code templates
    def create_languages(apps, schema_editor):
        Language = apps.get_model('core', 'Language')
        CodeTemplate = apps.get_model('core', 'CodeTemplate')

        c = Language.objects.create(name='C (GCC 9.2.0)', judge_language_id=75, ace_mode='c_cpp')
        cpp = Language.objects.create(name='C++ (GCC 9.2.0)', judge_language_id=76, ace_mode='c_cpp', concurrency_support=True)
        java = Language.objects.create(name='Java (OpenJDK 13.0.1)', judge_language_id=79, ace_mode='java')
        python3 = Language.objects.create(name='Python 3.8.1', judge_language_id=83, ace_mode='python')
        verilog = Language.objects.create(name='Verilog (Icarus Verilog 11.0.0)', judge_language_id=90, ace_mode='verilog')

        # create code templates
        c_template = CodeTemplate(language=c, name="Default",
                           code="// ro-start\n#include <stdio.h>\n#include <stdlib.h>\n\nint main(){\n// ro-end\n	// enter your solution here...\n\n\n// ro-start\n	return 0;\n}\n// ro-end\n")
        cpp_template = CodeTemplate(language=cpp, name="Default",
                           code="// ro-start\n#include <iostream>\n\nint main(){\n// ro-end\n	// enter your solution here...\n\n\n// ro-start\n	return 0;\n}\n// ro-end\n")
        java_template = CodeTemplate(language=java, name="Default",
                           code="// ro-start\npublic class Main {\n    public static void main(String [] args) {\n// ro-end\n        // enter your solution here...\n\n// ro-start\n    }\n}\n// ro-end\n")
        python_template = CodeTemplate(language=python3, name="Default",
                           code='# // ro-start\ndef main():\n# // ro-end\n	# enter your solution here...\n\n\n# // ro-start\nif __name__ == "__main__":\n	main()\n# // ro-end\n')
        verilog_template = CodeTemplate(language=verilog, name="Default",
                           code="module main (out, clk, reset);\n\n\toutput out;\n\tinput clk, reset;\n\n\talways @ (posedge clk)\n\tbegin\n\t\t//  enter your solution here...\n\n\n\tend\n\nendmodule")
        CodeTemplate.objects.bulk_create([c_template, cpp_template, java_template, python_template, verilog_template])


    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_groups),
        migrations.RunPython(create_admin),
        migrations.RunPython(create_users),
        migrations.RunPython(create_languages),
    ]
