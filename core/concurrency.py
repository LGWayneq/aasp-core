import re

def modify_concurrency_params(params, code, lang_id, test_case):
    params = append_concurrency_compiler_options(params, lang_id, test_case)
    params = process_concurrency_code(params, lang_id, code, test_case)
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
    # params["enable_per_process_and_thread_memory_limit"] = True
    return params

def process_concurrency_code(params, lang_id, code, test_case):
    # C
    if lang_id == 75:
        params['source_code'] = code
    # C++
    elif lang_id == 76:
        cpp_counter_init = """
#include <iostream>
#include <thread>
#include <mutex>
#include <string>

std::mutex createMtx;
std::mutex joinMtx;
int numThreadsCreated = 0;
"""
        cpp_counter_functions = """
template<typename Function, typename... Args>
std::thread createThread(Function&& func, Args&&... args) {
    std::lock_guard<std::mutex> lock(createMtx);
    std::thread newThread(func, args...);
    numThreadsCreated++;
    std::string AASP_NUM_THREADS_VALID_TOKEN("");
    if (numThreadsCreated == TEST_CASE.MIN_THREADS) {
        AASP_NUM_THREADS_VALID_TOKEN = "AASP_" + std::to_string(numThreadsCreated) + "_THREADS_CREATED_SUFFICIENT";
    } else if (numThreadsCreated < TEST_CASE.MIN_THREADS) {
        AASP_NUM_THREADS_VALID_TOKEN = "AASP_" + std::to_string(numThreadsCreated) + "_THREADS_CREATED_INSUFFICIENT";
    }
    std::cout << AASP_NUM_THREADS_VALID_TOKEN;
    return newThread;
}

void joinThread(std::thread& _thread) {
    std::lock_guard<std::mutex> lock(joinMtx);
    _thread.join();
}
"""
        cpp_counter_functions = cpp_counter_functions.replace("TEST_CASE.MIN_THREADS", str(test_case.min_threads))
        code = code.replace("int main() {", 'int main() { std::cout << "AASP_0_THREADS_CREATED_INSUFFICIENT";')
        params['source_code'] = cpp_counter_init + cpp_counter_functions + code
    return params

def evaluate_concurrency_results(stdout, expected_output, status_id):
    sufficient_threads = re.search(r'AASP_\d+_THREADS_CREATED_SUFFICIENT', stdout) is not None

    # remove thread counter tokens from output
    stdout = re.sub(r'AASP_\d+_THREADS_CREATED_SUFFICIENT', '', stdout)
    stdout = re.sub(r'AASP_\d+_THREADS_CREATED_INSUFFICIENT', '', stdout)

    # manually evaluate correctness
    if expected_output.strip() == stdout.strip() and status_id == 4:
        if sufficient_threads:
            status_id = 3
        else:
            status_id = 15
    
    return {
        stdout,
        status_id
    }