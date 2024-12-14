from flask import Flask, request, jsonify
import openai
import os
import json
from dotenv import load_dotenv
import re
import logging
from textblob import TextBlob
from threading import Lock
from datetime import datetime

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)
logging.basicConfig(filename="assistant.log", level=logging.INFO)

ORDERS_FILE = "orders1.json"
CUSTOMERS_FILE = "customers1.json"
ORDER_ID_FILE = "last_order_id.txt"
ORDER_ID_LOCK = Lock()

EXIT_PHRASES = ["exit", "quit", "bye", "goodbye", "thanks", "no, thanks"]

# Load and save JSON data
def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                logging.warning(f"Invalid JSON in {file_path}. Initializing empty.")
                return {}
    return {}

def save_data(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

# Generate a unique order ID
def generate_order_id():
    with ORDER_ID_LOCK:
        if not os.path.exists(ORDER_ID_FILE):
            with open(ORDER_ID_FILE, "w") as f:
                f.write("0000")
        with open(ORDER_ID_FILE, "r") as f:
            last_id = int(f.read().strip() or 0)
        new_id = f"{(last_id + 1):04d}"
        with open(ORDER_ID_FILE, "w") as f:
            f.write(new_id)
        return new_id

# Analyze sentiment
def is_negative_sentiment(user_input):
    return TextBlob(user_input).sentiment.polarity < -0.5

# Main conversation state (Flask endpoints will handle different states)
@app.route("/start", methods=["POST"])
def start_conversation():
    orders = load_data(ORDERS_FILE)
    customers = load_data(CUSTOMERS_FILE)
    data = request.get_json()
    phone_number = data.get("phone_number")
    user_message = data.get("message", "").lower()

    if not phone_number or not user_message:
        return jsonify({"error": "phone_number and message are required"}), 400

    if phone_number not in customers:
        customers[phone_number] = {"name": "Guest", "order_history": []}
        save_data(CUSTOMERS_FILE, customers)

    if any(phrase in user_message for phrase in EXIT_PHRASES):
        return jsonify({"response": "Thanks for visiting! Have a great day!"}), 200

    if is_negative_sentiment(user_message):
        return jsonify({"response": "I'm sorry to hear that. How can I assist you better?"}), 200

    if "order" in user_message or "pizza" in user_message:
        response = "What would you like to order? Please specify pizza size, toppings, and quantity."
        return jsonify({"response": response}), 200

    return jsonify({"response": "How can I assist you with your pizza order today?"}), 200

@app.route("/order", methods=["POST"])
def handle_order():
    orders = load_data(ORDERS_FILE)
    customers = load_data(CUSTOMERS_FILE)
    data = request.get_json()

    phone_number = data.get("phone_number")
    order_details = data.get("order_details")

    if not phone_number or not order_details:
        return jsonify({"error": "phone_number and order_details are required"}), 400

    order_id = generate_order_id()
    orders[order_id] = {
        "phone_number": phone_number,
        "order_details": order_details,
        "order_time": str(datetime.now()),
        "status": "Received"
    }
    save_data(ORDERS_FILE, orders)

    customers[phone_number]["order_history"].append(order_id)
    save_data(CUSTOMERS_FILE, customers)

    response = f"Your order has been placed successfully. Your order ID is {order_id}."
    return jsonify({"response": response}), 200

@app.route("/confirm", methods=["POST"])
def confirm_order():
    data = request.get_json()
    confirmation = data.get("confirmation", "").lower()

    if confirmation in ["yes", "y", "sure", "ok"]:
        return jsonify({"response": "Thank you! Your order is confirmed and will be ready soon!"}), 200
    return jsonify({"response": "No problem! Let us know if you'd like to make changes or order later."}), 200

@app.route("/menu", methods=["GET"])
def get_menu():
    menu = {
        "menu": [
            {"product": "Garlic Bread", "price": 4.11},
            {"product": "Caesar Salad", "price": 6.50},
            {"product": "Diet Coke", "price": 3.12},
            {"product": "Garlic Knots (6x)", "price": 5.20},
            {"product": "Chicken with Vodka Sauce Hero", "price": 10.92},
            {"product": "Cheese Pie (Large)", "price": 25.48},
            {"product": "Cheese Slice", "price": 3.82},
            {"product": "Buffalo Chicken Wrap", "price": 8.27},
            {"product": "Sicilian Slice", "price": 4.29},
            {"product": "Cannoli", "price": 3.82},
        ]
    }
    return jsonify(menu), 200

@app.route("/hello", methods=["GET"])
def say_hello():
    return jsonify({"message": "Hello, welcome to our Pizza Shop API!"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
