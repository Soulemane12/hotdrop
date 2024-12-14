import openai
import os
import json
import re
import logging
import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from textblob import TextBlob
from enum import Enum, auto
import threading

logging.basicConfig(
    filename='assistant.log',
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s'
)

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

ORDERS_FILE = "orders1.json"
CUSTOMERS_FILE = "customers1.json"
ORDER_ID_FILE = "last_order_id.txt"

ORDER_ID_LOCK = threading.Lock()

EXIT_PHRASES = [
    "exit", "quit", "bye", "goodbye", "see you", "later", "thanks",
    "thank you", "no, thanks", "i'm done", "that's all"
]

app = Flask(__name__)

# Load data function
def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                logging.warning(f"Warning: {file_path} is empty or contains invalid JSON.")
                return {}
    return {}

# Save data function
def save_data(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

# Generate Order ID
def generate_order_id():
    with ORDER_ID_LOCK:
        if not os.path.exists(ORDER_ID_FILE):
            with open(ORDER_ID_FILE, "w") as f:
                f.write("0000")

        with open(ORDER_ID_FILE, "r") as f:
            last_id = int(f.read().strip() or 0)

        new_id = last_id + 1
        with open(ORDER_ID_FILE, "w") as f:
            f.write(f"{new_id:04d}")
        return f"{new_id:04d}"

# Flask Routes
@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get("message", "")
    
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "user", "content": user_message}
            ]
        )
        response_text = completion.choices[0].message.content
        return jsonify({"response": response_text})
    except Exception as e:
        logging.error(f"OpenAI API error: {e}")
        return jsonify({"error": "Something went wrong with the OpenAI API."}), 500

@app.route('/orders', methods=['GET'])
def get_orders():
    try:
        orders = load_data(ORDERS_FILE)
        return jsonify(orders)
    except Exception as e:
        logging.error(f"Error fetching orders: {e}")
        return jsonify({"error": "Unable to fetch orders."}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000)
