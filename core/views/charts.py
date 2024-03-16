import json
import math
from datetime import timedelta
from django.db.models import Avg
from core.models import CodeQuestionAttempt, McqQuestionAttempt, CodeQuestion, McqQuestion

def generate_score_distribution_graph(scores, max_value, title = "Score Distribution", x_title = "Score", y_title = "Number of Students"):
    buckets = create_buckets(0, max_value)
    assign_buckets(buckets, [score for score in scores])
    y_values, x_values = get_bucket_items(buckets)

    return {
        "title": title,
        "x_title": x_title,
        "x_values": format_x_values(x_values),
        "y_title": y_title,
        "y_values": y_values,
    }

def generate_assessment_time_spent_graph(questions):
    num_of_questions = len(questions)
    x_values = [i+1 for i in range(num_of_questions)]
    y_values = [calculate_average_question_delta(question).total_seconds()/60 for question in questions]
    
    return {
        "title": "Average Time Spent per Question",
        "x_title": "Question",
        "x_values": format_x_values(x_values),
        "y_title": "Avg Time Spent (mins)",
        "y_values": y_values,
    }

def generate_thread_timelines(test_case_attempts):
    timelines = []
    for attempt in test_case_attempts:
        timelines.append(generate_thread_timeline(attempt.thread_times, attempt.time))

    return timelines

def generate_thread_timeline(thread_times_string, time):
    thread_times = thread_times_string.split("|")
    num_of_threads = len(thread_times)
    y_values = [[int(t)/1000 for t in start_end.split(",")] for start_end in thread_times]
    x_values = [i+1 for i in range(num_of_threads)]
    
    return {
        "title": "Thread Timeline",
        "x_title": "Time (ms)",
        "x_values": format_x_values(x_values),
        "y_title": "Thread",
        "y_values": y_values,
        "max_time": time * 1000
    }

def calculate_average_question_delta(question):
    if isinstance(question, CodeQuestion):
        valid_attempts = CodeQuestionAttempt.objects.filter(code_question=question, time_spent__gt=timedelta(seconds=0))
    elif isinstance(question, McqQuestion):
        valid_attempts = McqQuestionAttempt.objects.filter(mcq_question=question, time_spent__gt=timedelta(seconds=0))
    
    if len(valid_attempts) == 0:
        return timedelta(seconds=0)
    else:
        return valid_attempts.aggregate(Avg('time_spent'))['time_spent__avg']

def generate_question_time_spent_graph(question):
    if isinstance(question, CodeQuestion):
        all_time_spent = [delta.total_seconds()/60 for delta in CodeQuestionAttempt.objects \
            .filter(code_question=question, assessment_attempt__best_attempt=True, time_spent__gt=timedelta(seconds=0)) \
            .values_list('time_spent', flat=True)]
    elif isinstance(question, McqQuestion):
        all_time_spent = [delta.total_seconds()/60 for delta in McqQuestionAttempt.objects \
            .filter(mcq_question=question, assessment_attempt__best_attempt=True, time_spent__gt=timedelta(seconds=0)) \
            .values_list('time_spent', flat=True)]
    max_time_spent = max(all_time_spent) if len(all_time_spent) > 0 else 0
    buckets = create_buckets(0, math.ceil(max_time_spent))
    assign_buckets(buckets, all_time_spent)
    y_values, x_values = get_bucket_items(buckets)
    
    return {
        "title": "Time Spent Distribution",
        "x_title": "Time Spent (mins)",
        "x_values": format_x_values(x_values),
        "y_title": "Number of Students",
        "y_values": y_values,
    }

def format_x_values(x_values):
    return [ord(c) for c in json.dumps(x_values)]

def create_buckets(min_value, max_value):
    # Calculate the range of values
    value_range = max_value - min_value
    
    # Calculate the bucket size
    bucket_size = 1
    double = False
    while bucket_size * 15 < value_range:
        if double:
            bucket_size *= 2
        else:
            bucket_size *= 5
        double = not double
    
    # Create the buckets
    buckets = []
    for i in range(min_value, max_value, bucket_size):
        buckets.append({
            "min": i,
            "max": i+bucket_size,
            "count": 0,
        })
    
    if bucket_size == 1:
        buckets.append({
            "min": max_value,
            "max": max_value,
            "count": 0,
        })
    else:
        buckets[-1]["max"] = max_value

    return buckets

def assign_buckets(buckets, data):
    for value in data:
        for bucket in buckets:
            if value >= bucket["min"] and value < bucket["max"]:
                bucket["count"] += 1
                break
        if value == buckets[-1]["max"]:
            buckets[-1]["count"] += 1

def get_bucket_items(buckets):
    items = []
    labels = []
    for bucket in buckets:
        items.append(bucket["count"])
        if bucket["min"] + 1 >= bucket["max"]:
            labels.append(str(bucket["min"]))
        else:
            labels.append("{} - {}".format(bucket["min"], bucket["max"]))
    return items, labels

def calculate_median(values, key = lambda x: x):
    if values is None or len(values) == 0:
        return 0
    
    values = sorted([key(value) for value in values])
    if len(values) % 2 == 1:
        median = values[len(values)//2]
    else:
        median = (values[len(values)//2] + values[len(values)//2 - 1])/2

    return round(median, 2)

def calculate_mean(values, key = lambda x: x):
    if values is None or len(values) == 0:
        return 0
    total = sum([key(value) for value in values])
    mean = total / len(values)
    return round(mean, 2)