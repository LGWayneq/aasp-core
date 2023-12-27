import zipfile
import base64
import re

from vcdvcd.vcdvcd import VCDVCD
from math import floor, ceil

from core.models import CodeQuestion, CodeQuestionAttempt, McqQuestion, McqQuestionAttempt, CourseGroup, User
from core.models.questions import Language
from core.tasks import send_assessment_published_email


def is_student(user):
    return user.groups.filter(name='student').exists()


def is_educator(user):
    return user.is_superuser or user.groups.filter(name='educator').exists()


def is_lab_assistant(user):
    return user.groups.filter(name='lab_assistant').exists()


def clean_csv(rows):
    """
    Removes:
    - header row, if it exists
    - duplicated rows
    - rows with duplicated values in username (but different names, group, etc)
    """
    # stores all removed rows by this cleaning function
    removed = []

    # remove header row if it exists
    if "FIRST_NAME,LAST_NAME,USERNAME,GROUP" in rows[0]:
        del rows[0]

    # remove duplicated rows by converting to set
    rows = set(rows)

    # split rows into fields and remove rows that do not have exactly 4 fields
    cleaned = []
    for row in rows:
        fields = row.split(",")
        if len(fields) != 4:
            removed.append(fields)
        else:
            cleaned.append(fields)

    # find duplicated values in username (e.g. two different rows with same username, etc)
    seen_username = set()
    duplicates_username = [x[2] for x in cleaned if x[2] in seen_username or seen_username.add(x[2])]

    # remove rows with duplicated values in username
    cleaned2 = []
    for row in cleaned:
        if row[2] in duplicates_username:
            removed.append(row)
        else:
            cleaned2.append(row)

    return cleaned2, removed


def check_permissions_course(course, user):
    """
    Returns the permission level of a user for this course.
    0 - no permissions
    1 - maintainer
    2 - owner
    """
    if course.owner == user:
        return 2
    if user in course.maintainers.all():
        return 1
    return 0


def check_permissions_qb(question_bank, user):
    """
    Returns the permission level of a user for this question bank.
    0 - no permissions
    1 - owner shared with this user (viewing rights) or public
    2 - owner
    """
    if question_bank.owner == user:
        return 2
    if user in question_bank.shared_with.all() or question_bank.private is False:
        return 1
    return 0


def check_permissions_question(question, user):
    """
    Returns if a user can make changes to a code question.
    True - Has permission (is the owner of the question bank, or course containing the assessment)
    False - No permission
    2 - Read/Write
    1 - Read
    0 - No permissions
    """
    if question.question_bank:  # belongs to qb
        return check_permissions_qb(question.question_bank, user)
    else:  # belongs to assessment
        if check_permissions_course(question.assessment.course, user) != 0:
            return 2


def check_permissions_assessment(assessment, user):
    """
    Returns the permission level of a user for the course that this assessment belongs to.
    0 - no permissions
    1 - maintainer
    2 - owner
    """
    if assessment.course.owner == user:
        return 2
    if user in assessment.course.maintainers.all():
        return 1
    return 0


def get_question_instance(question_id):
    """
    Returns the question instance
    """
    code_question = CodeQuestion.objects.filter(id=question_id).first()
    if code_question:
        return code_question
    
    mcq_question = McqQuestion.objects.filter(id=question_id).first()
    if mcq_question:
        return mcq_question
    
    return None


def get_assessment_attempt_question(assessment_attempt, question_index=None):
    """
    Get a specific question in an assessment attempt.
    If question_index is specified and within bounds, return only the question object.
    Else, return the entire list.
    """
    mcq_attempts = list(McqQuestionAttempt.objects.filter(assessment_attempt=assessment_attempt).order_by('id').prefetch_related('mcq_question'))
    statuses = [mqa.attempted for mqa in mcq_attempts]

    cq_attempts = list(CodeQuestionAttempt.objects.filter(assessment_attempt=assessment_attempt).order_by('id').prefetch_related('code_question'))
    statuses += [cqa.attempted for cqa in cq_attempts]

    attempts = mcq_attempts + cq_attempts
    
    if question_index is None:  # return all questions
        return statuses, attempts
    elif question_index > len(attempts) - 1:  # return None
        return [], None
    else:  # return specific question
        return statuses, attempts[question_index]


def user_enrolled_in_course(course, user) -> bool:
    """Checks if a user is enrolled in a course."""
    return course.coursegroup_set.filter(students=user).exists()


def construct_assessment_published_email(assessment, recipients=None):
    """
    Gets the required parameters needed to send an email notification on the published assessment. The actual sending of email is queued as a Celery task.
    
    Parameters:
    -----------
    assessment : Assessment
        the assessment object.
    recipients : list, optional
        list of email recipients, defaults to None. 
        list is converted to list<dict> containing "email" and "name".
    """
    course_groups = CourseGroup.objects.filter(course=assessment.course).prefetch_related('course')
    students_enrolled = User.objects.filter(enrolled_groups__in=course_groups)
    
    if recipients is None and not students_enrolled:
        return
    
    if recipients is None:
        recipients = students_enrolled    

    for student in recipients:
            recipients = [
                {
                    "email": student.email,
                    "name": student.get_full_name(),
                }
            ]

    send_assessment_published_email.delay(assessment.id, assessment.name, str(assessment.course),\
                                          assessment.time_start, assessment.time_end, assessment.duration, recipients)

def construct_expected_output_judge0_params(test_case):
    # judge0 params
    code_question = CodeQuestion.objects.filter(id=test_case.code_question_id).first()
    if code_question is None or code_question.solution_code is None or code_question.solution_code_language is None:
        return None

    params = {
        "source_code": code_question.solution_code,
        "language_id": code_question.solution_code_language.judge_language_id,
        "stdin": test_case.stdin,
        "expected_output": test_case.stdout,
        "cpu_time_limit": test_case.time_limit,
        "memory_limit": test_case.memory_limit,
    }
    if test_case.code_question.is_concurrency_question:
        params = append_concurrency_compiler_options(params, code_question.solution_code_language.judge_language_id, test_case)

    return params

def construct_judge0_params(code, lang_id, test_case) -> dict:
    """
    Constructs the parameters needed to send to Judge0 API.
    Hardware description languages require a different set up, where the code is zipped and sent to Judge0.
    """
    if test_case.code_question.is_software_language():
        # judge0 params
        params = {
            "source_code": code,
            "language_id": lang_id,
            "stdin": test_case.stdin,
            "expected_output": test_case.stdout,
            "cpu_time_limit": test_case.time_limit,
            "memory_limit": test_case.memory_limit,
        }
        if test_case.code_question.is_concurrency_question:
            params = append_concurrency_compiler_options(params, lang_id, test_case)
    else:
        # check if language is verilog
        language = Language.objects.get(judge_language_id=lang_id)
        if language.name.find('Verilog') != -1:
            if code.find('$dumpfile') == -1 and test_case.stdin.find('$dumpfile') == -1:
                # add wave dump to testbench
                # find testbench file
                if code.find('initial') != -1:
                    # add wave dump to last line before endmodule
                    testbench = code.replace('endmodule', 'initial begin $dumpfile("vcd_dump.vcd"); $dumpvars(0); end endmodule')
                    main = test_case.stdin
                elif test_case.stdin.find('initial') != -1:
                    # add wave dump to last line before endmodule
                    main = code
                    testbench = test_case.stdin.replace('endmodule', 'initial begin $dumpfile("vcd_dump.vcd"); $dumpvars(0); end endmodule')
            else:
                # Define the regular expression patterns
                dumpfile_pattern = r'\$dumpfile\("[^"]+"\)'
                dumpvars_pattern = r'\$dumpvars\(\d+\)'

                # Replacement strings
                new_dumpfile = '$dumpfile("vcd_dump.vcd")'
                new_dumpvars = '$dumpvars(0)'

                if code.find('initial') != -1:
                    # replace wave dump
                    testbench = re.sub(dumpfile_pattern, new_dumpfile, code)
                    testbench = re.sub(dumpvars_pattern, new_dumpvars, testbench)
                    main = test_case.stdin
                elif test_case.stdin.find('initial') != -1:
                    # replace wave dump
                    testbench = re.sub(dumpfile_pattern, new_dumpfile, test_case.stdin)
                    testbench = re.sub(dumpvars_pattern, new_dumpvars, testbench)
                    main = code

        try:
            main, input_ports, output_ports = embed_inout_module(main)
            testbench = embed_inout_testbench(testbench, input_ports, output_ports)
        except:
            main = code
            testbench = test_case.stdin
        
        # create zip file
        with zipfile.ZipFile('submission.zip', 'w') as zip_file:
            zip_file.writestr('main.v', main)
            zip_file.writestr('testbench.v', testbench)
            zip_file.writestr('compile', 'iverilog -o a.out main.v testbench.v')
            zip_file.writestr('run', "vvp -n a.out | find -name '*.vcd' -exec python3 -m vcd2wavedrom.vcd2wavedrom --aasp -i {} + | tr -d '[:space:]'")
        
        # encode zip file
        with open('submission.zip', 'rb') as f:
            encoded = base64.b64encode(f.read()).decode('utf-8')

        # judge0 params
        params = {
            "additional_files": encoded,
            "language_id": lang_id,
            "stdin": test_case.stdin,
            "expected_output": test_case.stdout,
            "cpu_time_limit": test_case.time_limit,
            "memory_limit": test_case.memory_limit,
        }
    
    return params

def append_concurrency_compiler_options(params, lang_id, test_case):
    # C
    if lang_id == 75:
        params['compiler_options'] = "-pthread -fsanitize=thread"
    # C++
    elif lang_id == 76:
        params['compiler_options'] = "-fsanitize=thread"

    params["max_processes_and_or_threads"] = test_case.max_threads
    params["enable_per_process_and_thread_time_limit"] = True
    params["enable_per_process_and_thread_memory_limit"] = True
    return params

def embed_inout_module(module_code):
    """
    Find the inputs and outputs of a module and embed in_ and out_ in front of signal names to identify them easily.
    """
    # Define regular expressions to find input and output ports
    input_pattern = re.compile(r'\binput\s+\[?.*?\]?\s*([\w,\s]+);')
    output_pattern = re.compile(r'\boutput\s+\[?.*?\]?\s*([\w,\s]+);')

    # Find input and output port names using regular expressions
    input_ports_find = input_pattern.findall(module_code)
    output_ports_find = output_pattern.findall(module_code)

    # Combine multiple patterns into one
    port_pattern = re.compile(r'(\w+)\s+([\[\]\d:]+\s+)?(\w+)\s*')
    ports_find = port_pattern.findall(module_code)

    if len(input_ports_find) == 0 and len(output_ports_find) == 0 and len(ports_find) == 0:
        return module_code

    # Extract individual port names from the combined pattern results
    input_ports = [port[2] for port in ports_find if port[0] == 'input']
    output_ports = [port[2] for port in ports_find if port[0] == 'output']

    # Combine ports from multiple sources
    input_ports.extend([port.strip() for ports in input_ports_find for port in ports.split(',')])
    output_ports.extend([port.strip() for ports in output_ports_find for port in ports.split(',')])

    # Add 'in_' prefix to input port names
    renamed_input_ports = ['in_' + port.strip() for port in input_ports]

    # Add 'out_' prefix to output port names
    renamed_output_ports = ['out_' + port.strip() for port in output_ports]

    # Replace input and output port names in module code
    for old_port, new_port in zip(input_ports + output_ports, renamed_input_ports + renamed_output_ports):
        module_code = re.sub(r'\b' + re.escape(old_port) + r'\b', new_port, module_code)

    return module_code, input_ports, output_ports

def embed_inout_testbench(testbench_code, input_ports, output_ports):
    # Replace input and output port names in testbench code
    for old_port, new_port in zip(input_ports + output_ports, ['in_' + port.strip() for port in input_ports] + ['out_' + port.strip() for port in output_ports]):
        testbench_code = re.sub(r'\b' + re.escape(old_port) + r'\b', new_port, testbench_code)
    
    return testbench_code

def generate_module(module_name, ports):
    """
    Generate a Verilog module design text based on module name and ports.

    Args:
        module_name (str): The name of the Verilog module.
        ports (list): A list of dictionaries, where each dictionary represents a port.
                      Each port dictionary should have the following keys:
                      - 'name': The name of the port (str).
                      - 'direction': The direction of the port ('input', 'output', or 'inout').
                      - 'bus': Boolean indicating if it's a bus.
                      - 'msb': The most significant bit (int).
                      - 'lsb': The least significant bit (int).

    Returns:
        str: The Verilog module design text.
    """
    # Start building the module design text
    verilog_code = f"module {module_name} (\n"

    # Iterate over the ports and add them to the module
    for port in ports:
        port_name = port['name']
        port_direction = port['direction']
        is_bus = port['bus']
        msb = port['msb']
        lsb = port['lsb']

        # Construct the port declaration based on bus and direction
        if is_bus:
            port_declaration = f"\t{port_direction} [{msb}:{lsb}] {port_name},\n"
        else:
            port_declaration = f"\t{port_direction} {port_name},\n"

        verilog_code += port_declaration

    # Remove the trailing comma and newline from the last port
    verilog_code = verilog_code.rstrip(',\n')

    # Close the module and return the Verilog code
    verilog_code += "\n);\n\n\n\nendmodule\n"

    return verilog_code

class TestbenchGenerator:
    def __init__(self, module_code):
        self.module_code = module_code
        self.testbench = ""
        self.mod_name = ""
        self.pin_list = []
        self.clock_name = ""
        self.reset_name = ""
        self.parser()

    def __call__(self):
        self.print_module_head()
        self.print_wires()
        self.print_dut()
        self.print_stimulus_block()
        self.print_clock_gen()
        self.print_module_end()

        return self.testbench

    def clean_module(self, cont):
        ## clean '// ...'
        cont = re.sub(r"//[^\n^\r]*", '\n', cont)
        ## clean '/* ... */'
        cont = re.sub(r"/\*.*\*/", '', cont)
        ## clean '`define ..., etc.'
        #cont = re.sub(r"[^\n^\r]+`[^\n^\r]*", '\n', cont)
        ## clean tables
        cont = re.sub(r'    +', ' ', cont)
        ## clean '\n' * '\r'
        cont = re.sub(r'[\n\r]+', '', cont)
        return cont
    
    def parser(self):
        # print vf_cont 
        mod_pattern = r"module[\s]+(\S*)[\s]*\([^\)]*\)[\s\S]*"  
        
        module_result = re.findall(mod_pattern, self.clean_module(self.module_code))
        #print module_result
        self.mod_name = module_result[0]
        
        self.parser_inoutput()
        self.find_clk_rst()

    def parser_inoutput(self):
        pin_list = self.clean_module(self.module_code) 

        comp_pin_list_pre = []
        for match in re.finditer(r'\b(input|output|inout)\s+([^;]+?)(?=[;]|input|output|inout|$)', pin_list):
            direction = match.group(1)
            ports = match.group(2)
            # remove bus and store bus
            bus = re.findall(r'\[[^\]]*\]', ports)
            if len(bus) != 0:
                bus = bus[0]
            else:
                bus = ''
            ports = re.sub(r'\[[^\]]*\]', '', ports)
            # remove reg
            ports = re.sub(r'reg[\s]*', '', ports)
            # split by ','
            ports = ports.split(',')
            
            for port in ports:
                if port != '\t' and port.strip() != '':
                    # remove space and brackets
                    port = re.sub(r'[\[\]\(\) ]', '', port)
                    comp_pin_list_pre.append((direction, bus + port))

        comp_pin_list = []
        type_name = ['reg', 'wire', 'wire', "ERROR"]
        for i in comp_pin_list_pre:
            x = re.split(r']', i[1])
            type = 0;
            if i[0] == 'input':
                type = 0
            elif i[0] == 'output':
                type = 1
            elif i[0] == 'inout':
                type = 2
            else:
                type = 3

            if len(x) == 2:
                x[1] = re.sub('[\s]*', '', x[1])
                comp_pin_list.append((i[0], x[1], x[0] + ']', type_name[type]))
            else:
                comp_pin_list.append((i[0], x[0], '', type_name[type]))
        
        self.pin_list = comp_pin_list

    def print_dut(self):
        max_len = 0
        for cpin_name in self.pin_list:
            pin_name = cpin_name[1]
            if len(pin_name) > max_len:
                max_len = len(pin_name)
        
        
        self.testbench +=  "\t%s uut (\n" % self.mod_name 
        
        align_cont = self.align_print(list(map(lambda x:("\t\t", "." + x[1], "(", x[1], '),'), self.pin_list)), 2)
        align_cont = align_cont[:-2] + "\n"
        self.testbench +=  align_cont
        
        self.testbench +=  "\t);\n" 
    
    def print_wires(self):
        self.testbench += self.align_print(list(map(lambda x:('\t', x[3], x[2], x[1], ';'), self.pin_list)), 1)
        self.testbench += "\n"
    
    def print_clock_gen(self):
        if not self.clock_name:
            clock_gen_text = "\n\treg CLK = 0;\n\talways #5 CLK = ~CLK;\n\n"
            self.testbench += clock_gen_text
        else:
            clock_gen_text = "\n\talways #5 CLK = ~CLK;\n\n"
            self.testbench += re.sub('CLK', self.clock_name, clock_gen_text)

    def print_stimulus_block(self):
        input_init_text = "\n".join([f"\t\t{port[1]} = 0;" for port in self.pin_list if port[0] == 'input'])
        stimulus_block_text = "\n\tinitial begin\n\t\t// Initialize Inputs\n%s\n\n\t\t// Add stimulus here\n\n\n\t\t$finish; \n\tend\n" % input_init_text
        self.testbench += stimulus_block_text
        
    def find_clk_rst(self):
        for pin in self.pin_list:
            if re.match(r'[\S]*(clk|clock)[\S]*', pin[1]):
                self.clock_name = pin[1]
                break

        for pin in self.pin_list:
            if re.match(r'rst|reset', pin[1]):
                self.reset_name = pin[1]
                break

    def print_module_head(self):
        self.testbench += "`timescale 1ns / 1ns\n\nmodule tb_%s;\n\n" % self.mod_name
        
    def print_module_end(self):
        self.testbench += "endmodule\n"

    def align_print(self, content, indent):
        """ Align pretty print."""

        row_len = len(content)
        col_len = len(content[0])
        align_cont = [""] * row_len
        for i in range(col_len):
            col = list(map(lambda x:x[i], content))
            max_len = max(map(len, col))
            for i in range(row_len):
                l = len(col[i])
                if col[i] == "\t":
                    align_cont[i] += "\t"
                else:
                    align_cont[i] += "%s%s" % (col[i], (indent + max_len - l) * ' ')
        
        # remove space in line end
        align_cont = list(map(lambda s:re.sub('[ ]*$', '', s), align_cont))
        return "\n".join(align_cont) + "\n"