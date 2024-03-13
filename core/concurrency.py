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
        c_counter_init = """
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <sys/time.h>

pthread_mutex_t createMtx = PTHREAD_MUTEX_INITIALIZER;
pthread_mutex_t joinMtx = PTHREAD_MUTEX_INITIALIZER;
int numThreadsCreated = 0;
"""
        hash_table_def = """
#include <stdint.h>

#define HASH_TABLE_SIZE 200

typedef struct Entry {
    pthread_t thread_id;
    long long microseconds;
    struct Entry* next;
} Entry;

typedef struct {
    Entry* table[HASH_TABLE_SIZE];
} ThreadStartsMap;

unsigned int hash(pthread_t thread_id) {
    return thread_id % HASH_TABLE_SIZE;
}

void map_put(ThreadStartsMap* map, pthread_t thread_id, long long microseconds) {
    unsigned int index = hash(thread_id);
    Entry* new_entry = malloc(sizeof(Entry));
    if (!new_entry) {
        exit(EXIT_FAILURE);
    }
    new_entry->thread_id = thread_id;
    new_entry->microseconds = microseconds;
    new_entry->next = map->table[index];
    map->table[index] = new_entry;
}

long long map_get(ThreadStartsMap* map, pthread_t thread_id) {
    unsigned int index = hash(thread_id);
    Entry* entry = map->table[index];
    while (entry) {
        if (entry->thread_id == thread_id) {
            return entry->microseconds;
        }
        entry = entry->next;
    }
    return NULL;
}

ThreadStartsMap threatStarts = { 0 };
"""
        c_time_functions = """
long long getCurrentTime() {
    struct timeval currentTime;
    gettimeofday(&currentTime, NULL);
    return currentTime.tv_sec * 1000000 + currentTime.tv_usec;
}

void setThreadStart(pthread_t _thread) {
    long long currentTime = getCurrentTime();
    map_put(&threatStarts, _thread, currentTime);
}

long long getThreadElapsed(pthread_t threadId) {
    long long currentTime = getCurrentTime();
    long long threadStart = map_get(&threatStarts, threadId);
    return currentTime - threadStart;
}
"""
        c_counter_functions = """
void* createThread(void* (*func)(void*), void* args) {
    pthread_mutex_lock(&createMtx);
    
    pthread_t newThread;
    pthread_create(&newThread, NULL, func, args);
    setThreadStart(newThread);
    numThreadsCreated++;
    
    char AASP_NUM_THREADS_VALID_TOKEN[50];
    
    if (numThreadsCreated >= TEST_CASE.MIN_THREADS) {
        sprintf(AASP_NUM_THREADS_VALID_TOKEN, "AASP_%d_THREADS_CREATED_SUFFICIENT", numThreadsCreated);
    } else {
        sprintf(AASP_NUM_THREADS_VALID_TOKEN, "AASP_%d_THREADS_CREATED_INSUFFICIENT", numThreadsCreated);
    }
    
    printf("%s", AASP_NUM_THREADS_VALID_TOKEN);
    
    pthread_mutex_unlock(&createMtx);
    return (void*)newThread;
}

void joinThread(void* _thread) {
    pthread_mutex_lock(&joinMtx);
    pthread_join(*(pthread_t*)_thread, NULL);
    long long timeElapsed = getThreadElapsed(_thread);
    printf("AASP_ELAPSED_THREAD_%lu_%lu", (unsigned long)_thread, timeElapsed);
    pthread_mutex_unlock(&joinMtx);
}
"""
        c_counter_functions = c_counter_functions.replace("TEST_CASE.MIN_THREADS", str(test_case.min_threads))
        code = code.replace("int main() {", 'int main() { printf("AASP_0_THREADS_CREATED_INSUFFICIENT");')
        params['source_code'] = c_counter_init + hash_table_def + c_time_functions + c_counter_functions + code
    # C++
    elif lang_id == 76:
        cpp_counter_init = """
#include <iostream>
#include <thread>
#include <mutex>
#include <string>
#include <unordered_map>
#include <chrono>
#include <unistd.h>
#include <fstream>

std::mutex createMtx;
std::mutex joinMtx;
int numThreadsCreated = 0;
std::unordered_map<std::thread::id, std::chrono::microseconds::rep> threadStarts;
"""
        cpp_time_functions = """
std::chrono::microseconds::rep getCurrentTime() {
    return std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
}

void setThreadStart(std::thread& _thread) {
    std::chrono::microseconds::rep currentTime = getCurrentTime();
    threadStarts[_thread.get_id()] = currentTime;
}

std::chrono::microseconds::rep getThreadElapsed(std::thread::id threadId) {
    std::chrono::microseconds::rep currentTime = getCurrentTime();
    std::chrono::microseconds::rep threadStart = threadStarts[threadId];
    return currentTime - threadStart;
}
"""
        cpp_counter_functions = """
template<typename Function, typename... Args>
std::thread createThread(Function&& func, Args&&... args) {
    std::lock_guard<std::mutex> lock(createMtx);
    std::thread newThread(func, args...);
    setThreadStart(newThread);
    numThreadsCreated++;
    std::string AASP_NUM_THREADS_VALID_TOKEN("");
    if (numThreadsCreated >= TEST_CASE.MIN_THREADS) {
        AASP_NUM_THREADS_VALID_TOKEN = "AASP_" + std::to_string(numThreadsCreated) + "_THREADS_CREATED_SUFFICIENT";
    } else if (numThreadsCreated < TEST_CASE.MIN_THREADS) {
        AASP_NUM_THREADS_VALID_TOKEN = "AASP_" + std::to_string(numThreadsCreated) + "_THREADS_CREATED_INSUFFICIENT";
    }
    std::cout << AASP_NUM_THREADS_VALID_TOKEN;
    return newThread;
}

void joinThread(std::thread& _thread) {
    std::lock_guard<std::mutex> lock(joinMtx);
    std::thread::id threadId = _thread.get_id();
    _thread.join();
    std::chrono::microseconds::rep timeElapsed = getThreadElapsed(threadId);
    std::cout << "AASP_ELAPSED_THREAD_" << threadId << "_" << timeElapsed;
}
"""
        cpp_counter_functions = cpp_counter_functions.replace("TEST_CASE.MIN_THREADS", str(test_case.min_threads))
        
        code = code.replace("int main() {", 'int main() { std::cout << "AASP_0_THREADS_CREATED_INSUFFICIENT";')
        params['source_code'] = cpp_counter_init + cpp_time_functions + cpp_counter_functions + code
    return params

def evaluate_concurrency_results(stdout, expected_output, status_id, stderr):
    sufficient_threads = re.search(r'AASP_\d+_THREADS_CREATED_SUFFICIENT', stdout) is not None

    # remove thread counter tokens from output
    stdout = re.sub(r'AASP_\d+_THREADS_CREATED_SUFFICIENT', '', stdout)
    stdout = re.sub(r'AASP_\d+_THREADS_CREATED_INSUFFICIENT', '', stdout)

    # remove thread elapsed time tokens from output
    stdout, thread_times = process_concurrency_thread_times(stdout)

    # manually evaluate correctness
    valid = True
    stdout_lines = stdout.strip().splitlines()
    expected_output_lines = expected_output.strip().splitlines()

    if len(stdout_lines) == len(expected_output_lines):
        for i in range(len(stdout_lines)):
            if stdout_lines[i].strip() != expected_output_lines[i].strip():
                valid = False
                break

    # check for sufficient thread usage        
    if valid and status_id == 4:
        if sufficient_threads:
            status_id = 3
        else:
            status_id = 15
    
    # check for data race
    if stderr and "data race" in stderr.lower():
        status_id = 16

    return {
        "stdout": stdout,
        "status_id": status_id,
        "thread_times": thread_times,
    }

def process_concurrency_thread_times(stdout):
    thread_times = []
    elapsed_tokens = re.findall(r'AASP_ELAPSED_THREAD_(\d+)_([0-9]+)', stdout)
    for token in elapsed_tokens:
        elapsed_time = token[1]
        thread_times.append(elapsed_time)
    
    stdout = re.sub(r'AASP_ELAPSED_THREAD_(\d+)_([0-9]+)', '', stdout)
    return stdout, thread_times

def get_max_threads_used(stdout):
    max_threads_used = 0
    insufficient_tokens = re.findall(r'AASP_\d+_THREADS_CREATED_INSUFFICIENT', stdout)
    for token in insufficient_tokens:
        max_threads_used = max(max_threads_used, int(re.search(r'\d+', token).group(0)))
    sufficient_tokens = re.findall(r'AASP_\d+_THREADS_CREATED_SUFFICIENT', stdout)
    for token in sufficient_tokens:
        max_threads_used = max(max_threads_used, int(re.search(r'\d+', token).group(0)))
    return max_threads_used