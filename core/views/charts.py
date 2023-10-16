import json
import math
from django.db.models import Avg
from core.models import CodeQuestionAttempt

def generate_score_distribution_graph(attempts, max_value, title = "Score Distribution", x_title = "Score", y_title = "Number of Students"):
    buckets = create_buckets(0, max_value)
    assign_buckets(buckets, [attempt.score for attempt in attempts])
    y_values, x_values = get_bucket_items(buckets)

    return {
        "title": title,
        "x_title": x_title,
        "x_values": format_x_values(x_values),
        "y_title": y_title,
        "y_values": y_values,
    }

def generate_assessment_time_spent_graph(code_questions):
    x_values = [i+1 for i in range(len(code_questions))]
    y_values = [delta.total_seconds()/60 for delta in CodeQuestionAttempt.objects \
        .filter(code_question__in=code_questions) \
        .values('code_question') \
        .annotate(avg_time_spent=Avg('time_spent')) \
        .order_by('code_question__id')
        .values_list('avg_time_spent', flat=True)]
    
    return {
        "title": "Average Time Spent per Question",
        "x_title": "Question",
        "x_values": format_x_values(x_values),
        "y_title": "Avg Time Spent (mins)",
        "y_values": y_values,
    }

def generate_question_time_spent_graph(code_question):
    all_time_spent = [delta.total_seconds()/60 for delta in CodeQuestionAttempt.objects \
        .filter(code_question=code_question) \
        .values_list('time_spent', flat=True)]
    buckets = create_buckets(0, math.ceil(max(all_time_spent)))
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