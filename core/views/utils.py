import zipfile
import base64
import re

from vcdvcd.vcdvcd import VCDVCD
from math import floor, ceil

from core.models import CodeQuestion, CodeQuestionAttempt, CourseGroup, User
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


def check_permissions_code_question(code_question, user):
    """
    Returns if a user can make changes to a code question.
    True - Has permission (is the owner of the question bank, or course containing the assessment)
    False - No permission
    2 - Read/Write
    1 - Read
    0 - No permissions
    """
    if code_question.question_bank:  # belongs to qb
        return check_permissions_qb(code_question.question_bank, user)
    else:  # belongs to assessment
        if check_permissions_course(code_question.assessment.course, user) != 0:
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


def get_assessment_attempt_question(assessment_attempt, question_index=None):
    """
    Get a specific question in an assessment attempt.
    If question_index is specified and within bounds, return only the question object.
    Else, return the entire list.
    """
    questions = []
    cq_attempts = list(
        CodeQuestionAttempt.objects.filter(assessment_attempt=assessment_attempt).order_by('id').prefetch_related(
            'code_question'))
    statuses = [cqa.attempted for cqa in cq_attempts]

    if question_index is None:  # return all questions
        return statuses, cq_attempts
    elif question_index > len(cq_attempts) - 1:  # return None
        return [], None
    else:  # return specific question
        return statuses, cq_attempts[question_index]


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
        params['compiler_options'] = "-fsanitize=thread"

    return params

def construct_judge0_params(request, test_case) -> dict:
    """
    Constructs the parameters needed to send to Judge0 API.
    Hardware description languages require a different set up, where the code is zipped and sent to Judge0.
    """
    if test_case.code_question.is_software_language() == True:
        # judge0 params
        params = {
            "source_code": request.POST.get('code'),
            "language_id": request.POST.get('lang-id'),
            "stdin": test_case.stdin,
            "expected_output": test_case.stdout,
            "cpu_time_limit": test_case.time_limit,
            "memory_limit": test_case.memory_limit,
        }
        if test_case.code_question.is_concurrency_question:
            params['compiler_options'] = "-fsanitize=thread"
    else:
        # check if language is verilog
        language = Language.objects.get(judge_language_id=request.POST.get('lang-id'))
        if language.name.find('Verilog') != -1:
            if request.POST.get('code').find('$dumpfile') == -1 and test_case.stdin.find('$dumpfile') == -1:
                # add wave dump to testbench
                # find testbench file
                if request.POST.get('code').find('initial') != -1:
                    # add wave dump to last line before endmodule
                    testbench = request.POST.get('code').replace('endmodule', 'initial begin $dumpfile("vcd_dump.vcd"); $dumpvars(0); end endmodule')
                    main = test_case.stdin
                elif test_case.stdin.find('initial') != -1:
                    # add wave dump to last line before endmodule
                    main = request.POST.get('code')
                    testbench = test_case.stdin.replace('endmodule', 'initial begin $dumpfile("vcd_dump.vcd"); $dumpvars(0); end endmodule')
            else:
                # Define the regular expression patterns
                dumpfile_pattern = r'\$dumpfile\("[^"]+"\)'
                dumpvars_pattern = r'\$dumpvars\(\d+\)'

                # Replacement strings
                new_dumpfile = '$dumpfile("vcd_dump.vcd")'
                new_dumpvars = '$dumpvars(0)'

                if request.POST.get('code').find('initial') != -1:
                    # replace wave dump
                    testbench = re.sub(dumpfile_pattern, new_dumpfile, request.POST.get('code'))
                    testbench = re.sub(dumpvars_pattern, new_dumpvars, testbench)
                    main = test_case.stdin
                elif test_case.stdin.find('initial') != -1:
                    # replace wave dump
                    testbench = re.sub(dumpfile_pattern, new_dumpfile, test_case.stdin)
                    testbench = re.sub(dumpvars_pattern, new_dumpvars, testbench)
                    main = request.POST.get('code')

        main, input_ports, output_ports = embed_inout_module(main)
        testbench = embed_inout_testbench(testbench, input_ports, output_ports)
        
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
            "language_id": request.POST.get('lang-id'),
            "stdin": test_case.stdin,
            "expected_output": test_case.stdout,
            "cpu_time_limit": test_case.time_limit,
            "memory_limit": test_case.memory_limit,
        }
    
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
    test_bench = ""

    # remove comments from module_code
    while("//" in module_code):
        module_code = module_code[:module_code.find("//")] + module_code[module_code.find("\n",module_code.find("//")) :]
    while("/*" in module_code):
        module_code = module_code[:module_code.find("/*")] + module_code[module_code.find("*/")+2:]

    module_code = " ".join(module_code.split()) #remove all white spaces

    # get module name
    module_name_start_index = module_code.find("module") + 6
    module_name_stop_index = module_code.find("(") if module_code.find("#") == -1  else module_code.find("#")
    module_name = module_code[module_name_start_index:module_name_stop_index].strip()

    # check if there is a clock signal 
    clk_signal = 1 if "clk" in module_code or "clock" in module_code else 0

    # check if there is a parameter
    parameter = 1 if "parameter" in module_code.lower() else 0

    # check for reset signal
    reset_signal = 1 if "reset" in module_code or "rst" in module_code else 0

    instance_name = 'uut' # default instance name

    # get the parameter list
    parameter_list = []
    if parameter:
        while(module_code.lower().find("parameter") != -1):
            parameter_list.append(module_code[module_code.lower().find("parameter")+10:module_code.find(";",module_code.lower().find("parameter"))].strip())
            module_code = module_code[module_code.find(";",module_code.lower().find("parameter"))+1:]

    ## trim the rtl code to get the inputs and outputs
    # first index
    if module_code.find("input") < module_code.find("output"):
        first_index = module_code.find("input")
    else:
        first_index = module_code.find("output")
    # last index
    if module_code.rfind("output") > module_code.rfind("input"):
        last_index = module_code.find(';',module_code.rfind("output"))+1 # 1 is added to include the semi-colon @ the end
    else:
        last_index = module_code.find(';',module_code.rfind("input"))+1
        
    module_code = module_code[first_index:last_index]

    module_code = [char for char in module_code if char != ' ' ] # convert the code to a list of characters

    input_vector=[]
    output_vector=[]

    temp = ''
    signal = ''
    size = ''
    discard_char = 1 # discard the first captured character


    for i, char in enumerate(module_code):
        temp = temp + char
    
        if "input" in temp and "output" in temp:
            temp = "input" if (temp.find("input") >  temp.find("output")) else "output"
            signal = ''
            size = ''
            discard_char = 1
            
        if temp.count("input") > 1 or temp.count("output") > 1 : 
            temp = "input" if "input" in temp else "output"
            signal = ''
            size = ''
            continue
            
        if char == ')' :
            if "input" in temp :
                input_vector.append(size + " " + signal)
            elif "output" in temp:
                output_vector.append(size + " " + signal)
            break
        
        if "input" in temp :
            if ']' in temp:
                size = temp[temp.find('['): temp.find(']')+1]
                signal = ''
                temp = "input"
            elif char == "," or char ==';':
                input_vector.append(size + " " + signal)
                signal = ''
            elif discard_char:
                discard_char  = 0
                continue
            else: 
                signal += char
        
        if "output" in temp :
            if ']' in temp:
                size = temp[temp.find('['): temp.find(']')+1]
                signal = ''
                temp = "output"
            elif char == ',' or char ==';':
                output_vector.append(size + " " + signal)
                signal = ''
            elif discard_char:
                discard_char  = 0
                continue
            else :
                signal += char

    # remove wire, reg from signals names
    for i,signal in enumerate(input_vector):
        if "wire" in signal:
            input_vector[i] = signal[signal.find("wire")+4:]
        elif "reg" in signal:
            input_vector[i] = signal[signal.find("reg")+3:]

    for i,signal in enumerate(output_vector):
        if "wire" in signal:
            output_vector[i] = signal[signal.find("wire")+4:]
        elif "reg" in signal:
            output_vector[i] = signal[signal.find("reg")+4:]

    test_bench += "`timescale 1ns / 1ns\n\n"
    test_bench += "module "
    test_bench += module_name+'_tb' + ';\n'

    ############ parameters declaration ############
    if parameter:
        test_bench += "\n\t// Parameters\n"
        for param in parameter_list:
            test_bench += "\tparameter "+param+';\n'

    ############ signals declaration ############
    test_bench += "\n\t// Inputs\n"
    for input in input_vector:
        test_bench += "\treg "+input+';\n'

    test_bench += "\n\t// Outputs\n"
    for output in output_vector:
        test_bench += "\twire "+ output+';\n'

    ############ instantiation ############
    test_bench += "\n\t// Instantiate the Unit Under Test (UUT)\n"
    test_bench += "\t" + module_name + ' ' + instance_name + " (\n"

    stripped_input = []
    stripped_output = []

    for input in input_vector:
        if ']' in input:
            input = input[input.find(']')+1:]
        input = input.strip()
        stripped_input.append(input)
        test_bench += "\t\t."+input+f'({input}),\n'

    for output in output_vector:
        if ']' in output:
            output = output[output.find(']')+1:]
        output = output.strip()
        stripped_output.append(output)
        test_bench += "\t\t."+output+f'({output}),'
    else:
        # remove the last comma
        test_bench = test_bench[:-1]
        test_bench += "\n"

    test_bench += "\t);"

    ############ clock generator block ############
    if clk_signal:
        test_bench += "\n\n\t// clock signal\n"
        test_bench += "\talways #5 clk = ~clk;" +'\n\n'

    test_bench += "\tinitial "+ "begin\n"
    test_bench += "\t\t// Initialize Inputs\n"

    for input in stripped_input:
        test_bench += "\t\t"+input+" = 0;\n"
        
    ############ wait for global reset  ############
    test_bench += "\n\t\t// Wait 20 ns for global reset to finish\n"
    test_bench += "\t\t#20;"
    test_bench += "\n\n\t\t// Add stimulus here\n\n"

    test_bench += "\t\t$finish; \n\tend" +'\n'

    ############ monitor block ############
    test_bench += "\n\tinitial\n"
    test_bench += "\t\t// Monitor output here to verify correctness\n"
    test_bench += "\t\t$monitor(\"%-0t" + ", %-0d" * len(stripped_output) + "\", $time" + "{1}{0}".format(", ".join(stripped_output), ", ") + ");\n\n"

    test_bench += "\nendmodule"

    return test_bench

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


class VCD2Wavedrom:

    busregex = re.compile(r'(.+)(\[|\()(\d+)(\]|\))')
    busregex2 = re.compile(r'(.+)\[(\d):(\d)\]')
    config = {}
    bit_open = None
    bit_close = None

    def __init__(self, config):
        self.config = config

    def replacevalue(self, wave, strval):
        if 'replace' in self.config and \
        wave in self.config['replace']:
            if strval in self.config['replace'][wave]:
                return self.config['replace'][wave][strval]
        return strval

    def group_buses(self, vcd_dict, slots):
        buses = {}
        buswidth = {}
        global bit_open
        global bit_close

        """
        Extract bus name and width
        """
        for isig, wave in enumerate(vcd_dict):
            result = self.busregex.match(wave)
            if result is not None and len(result.groups()) == 4:
                name = result.group(1)
                pos = int(result.group(3))
                self.bit_open = result.group(2)
                self.bit_close = ']' if self.bit_open == '[' else ')'
                if name not in buses:
                    buses[name] = {
                            'name': name,
                            'wave': '',
                            'data': []
                    }
                    buswidth[name] = 0
                if pos > buswidth[name]:
                    buswidth[name] = pos

        """
        Create hex from bits
        """
        for wave in buses:
            for slot in range(slots):
                if not self.samplenow(slot):
                    continue
                byte = 0
                strval = ''
                for bit in range(buswidth[wave]+1):
                    if bit % 8 == 0 and bit != 0:
                        strval = format(byte, 'X')+strval
                        byte = 0
                    val = vcd_dict[wave+self.bit_open+str(bit)+self.bit_close][slot][1]
                    if val != '0' and val != '1':
                        byte = -1
                        break
                    byte += pow(2, bit % 8) * int(val)
                strval = format(byte, 'X')+strval
                if byte == -1:
                    buses[wave]['wave'] += 'x'
                else:
                    strval = self.replacevalue(wave, strval)
                    if len(buses[wave]['data']) > 0 and \
                        buses[wave]['data'][-1] == strval:
                        buses[wave]['wave'] += '.'
                    else:
                        buses[wave]['wave'] += '='
                        buses[wave]['data'].append(strval)
        return buses

    def auto_config_waves(self, vcd_dict):
        startTime = -1
        syncTime = -1
        endTime = -1
        minDiffTime = -1

        """
        Warning: will overwrite all information from config file if any
        Works best with full synchronous signals
        """

        self.config['filter'] = ['__all__']
        self.config['clocks'] = []
        self.config['signal'] = []

        for isig, wave in enumerate(vcd_dict):
            wave_points = vcd_dict[wave]
            if len(wave_points) == 0:
                raise ValueError(f"Signal {wave} is empty!")
            wave_first_point = wave_points[0]
            wave_first_time = wave_first_point[0]
            if (startTime < 0) or (wave_first_time < startTime):
                startTime = wave_first_time

            if (len(wave_points) > 1) and ((syncTime < 0) or (wave_points[1][0] < syncTime)):
                syncTime = wave_points[1][0]

            for wave_point in wave_points:
                if (endTime < 0) or (wave_point[0] > endTime):
                    endTime = wave_point[0]

            for tidx in range(2, len(wave_points)):
                tmpDiff = wave_points[tidx][0] - wave_points[tidx - 1][0]
                if (wave_points[tidx - 1][0] >= startTime):
                    if ((minDiffTime < 0) or (tmpDiff < minDiffTime)) and (tmpDiff > 0):
                        minDiffTime = tmpDiff

        # Corner case
        if minDiffTime < 0:
            for tidx in range(1, len(wave_points)):
                tmpDiff = wave_points[tidx][0] - wave_points[tidx - 1][0]
                if (wave_points[tidx - 1][0] >= startTime):
                    if ((minDiffTime < 0) or (tmpDiff < minDiffTime)) and (tmpDiff > 0):
                        minDiffTime = tmpDiff

        # 1st loop to refine minDiffTime for async design or multiple async clocks
        tmpRatio = 1
        tmpReal = 0
        for isig, wave in enumerate(vcd_dict):
            wave_points = vcd_dict[wave]
            for wave_point in wave_points:
                tmpReal = (wave_point[0] - syncTime) / minDiffTime / tmpRatio
                if abs(tmpReal - round(tmpReal)) > 0.25:
                    # not too much otherwise un-readable
                    if tmpRatio < 4:
                        tmpRatio = tmpRatio * 2

        minDiffTime = minDiffTime / tmpRatio
        startTime = syncTime - \
            ceil((syncTime - startTime) / minDiffTime) * minDiffTime

        # 2nd loop to apply rounding
        tmpReal = 0
        for isig, wave in enumerate(vcd_dict):
            wave_points = vcd_dict[wave]
            for wave_point in wave_points:
                tmpReal = (wave_point[0] - startTime) / minDiffTime
                wave_point[0] = round(tmpReal)
            wave_points[0][0] = 0

        if 'maxtime' in self.config and self.config['maxtime'] is not None:
            self.config['maxtime'] = min(
                ceil((endTime - startTime) / minDiffTime), self.config['maxtime'])
        else:
            self.config['maxtime'] = ceil((endTime - startTime) / minDiffTime)

        return 1

    def homogenize_waves(self, vcd_dict, timescale):
        slots = int(self.config['maxtime']/timescale) + 1
        for isig, wave in enumerate(vcd_dict):
            lastval = 'x'
            for tidx, t in enumerate(range(0, self.config['maxtime'] + timescale, timescale)):
                if len(vcd_dict[wave]) > tidx:
                    newtime = vcd_dict[wave][tidx][0]
                else:
                    newtime = t + 1
                if newtime != t:
                    for ito_padd, padd in enumerate(range(t, newtime, timescale)):
                        vcd_dict[wave].insert(tidx+ito_padd, (padd, lastval))
                else:
                    lastval = vcd_dict[wave][tidx][1]
            vcd_dict[wave] = vcd_dict[wave][0:slots]


    def includewave(self, wave):
        if '__top__' in self.config['filter'] or ('top' in self.config and self.config['top']):
            return wave.count('.') <= 1
        elif '__all__' in self.config['filter'] or wave in self.config['filter']:
            return True
        return False


    def clockvalue(self, wave, digit):
        if wave in self.config['clocks'] and digit == '1':
            return 'P'
        return digit


    def samplenow(self, tick):
        offset = 0
        if 'offset' in self.config:
            offset = self.config['offset']

        samplerate = 1
        if 'samplerate' in self.config:
            samplerate = self.config['samplerate']

        if (tick - offset) >= 0 and (tick - offset) % samplerate <= 0:
            return True
        return False


    def appendconfig(self, wave):
        wavename = wave['name']
        if wavename in self.config['signal']:
            wave.update(self.config['signal'][wavename])

    def dump_wavedrom(self, vcd_dict, vcd_dict_types, timescale):
        drom = {'signal': [], 'config': {'hscale': 1}}
        slots = int(self.config['maxtime']/timescale)
        buses = self.group_buses(vcd_dict, slots)
        """
        Replace old signals that were grouped
        """
        for bus in buses:
            pattern = re.compile(r"^" + re.escape(bus) +
                                 "\\"+self.bit_open+".*")
            for wave in list(vcd_dict.keys()):
                if pattern.match(wave) is not None:
                    del vcd_dict[wave]
        """
        Create waveforms for the rest of the signals
        """
        idromsig = 0
        for wave in vcd_dict:
            if not self.includewave(wave):
                continue
            drom['signal'].append({
                'name': wave,
                'wave': '',
                'data': []
            })
            lastval = ''
            isbus = self.busregex2.match(
                wave) is not None or vcd_dict_types[wave] == 'bus'
            for j in vcd_dict[wave]:
                if not self.samplenow(j[0]):
                    continue
                digit = '.'
                value = None
                try:
                    value = int(j[1])
                    value = format(int(j[1], 2), 'X')
                except:
                    pass
                if value is None:
                    try:
                        value = float(j[1])
                        value = "{:.3e}".format(float(j[1]))
                    except:
                        pass
                if value is None:
                    value = j[1]
                if isbus or vcd_dict_types[wave] == 'string':
                    if lastval != j[1]:
                        digit = '='
                        if 'x' not in j[1]:
                            drom['signal'][idromsig]['data'].append(value)
                        else:
                            digit = 'x'
                else:
                    j = (j[0], self.clockvalue(wave, j[1]))
                    if lastval != j[1]:
                        digit = j[1]
                drom['signal'][idromsig]['wave'] += digit
                lastval = j[1]
            idromsig += 1

        """
        Insert buses waveforms
        """
        for bus in buses:
            if not self.includewave(bus):
                continue
            drom['signal'].append(buses[bus])

        """
        Order per config and add extra user parameters
        """
        ordered = []
        if '__all__' in self.config['filter']:
            ordered = drom['signal']
        else:
            for filtered in self.config['filter']:
                for wave in drom['signal']:
                    if wave['name'] == filtered:
                        ordered.append(wave)
                        self.appendconfig(wave)
        drom['signal'] = ordered
        if 'hscale' in self.config:
            drom['config']['hscale'] = self.config['hscale']

        return drom

    def execute(self, auto):
        vcd = VCDVCD(vcd_string=self.config['input_text'])
        timescale = int(vcd.timescale['magnitude'])
        vcd_dict = {}
        vcd_dict_types = {}
        vcd = vcd.data
        for i in vcd:
            if i != '$end':
                if int(vcd[i].size) > 1:
                    vcd_dict_types[vcd[i].references[0]] = 'bus'
                else:
                    vcd_dict_types[vcd[i].references[0]] = 'signal'
                vcd_dict[vcd[i].references[0]] = [list(tv) for tv in vcd[i].tv]

        if auto:
            timescale = self.auto_config_waves(vcd_dict)

        self.homogenize_waves(vcd_dict, timescale)
        return self.dump_wavedrom(vcd_dict, vcd_dict_types, timescale)
    
def vcd2wavedrom(vcd):
    # find the last changed time
    for line in vcd.strip().split('\n')[::-1]:
        if line.startswith('#'):
            last_changed_time = int(line[1:])
            break  # Stop searching once the last timestamp is found
    
    sample_rate = last_changed_time // 10
    config = {
        'input_text': vcd,
        'samplerate': 1,
    }

    vcd2wavedrom = VCD2Wavedrom(config)
    return vcd2wavedrom.execute(auto=True)