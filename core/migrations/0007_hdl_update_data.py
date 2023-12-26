# Data Migration file for updating the existing language data

from django.db import migrations

class Migration(migrations.Migration):

    # update HDL languages
    def update_languages(apps, schema_editor):
        Language = apps.get_model('core', 'Language')
        CodeTemplate = apps.get_model('core', 'CodeTemplate')

        verilog = Language.objects.get(name='Verilog (Icarus Verilog 11.0.0)')

        # create code templates
        CodeTemplate.objects.update_or_create(language=verilog, name="Module",
                           defaults={"code": "module main(clk, reset, out);\n\n\tinput clk, reset;\n\toutput out;\n\n\t// enter your solution here...\n\n\nendmodule"})
        CodeTemplate.objects.create(language=verilog, name="Testbench",
                           code="module main_tb;\n\n\treg clk, reset;\n\twire out;\n\n\tmain uut (.clk(clk), .reset(reset), .out(out));\n\n\tinitial begin\n\t\t//  enter your solution here...\n\n\n\tend\n\nendmodule")

    dependencies = [
        ('core', '0006_hdl_question_config'),
    ]

    operations = [
        migrations.RunPython(update_languages)
    ]

