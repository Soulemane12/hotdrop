from flask import Flask, request, jsonify
import os
import json
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# File paths
ORDERS_FILE = "orders1.json"
CUSTOMERS_FILE = "customers1.json"

# Load data functions
def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            try:
                return json.load(file)
            except json.JSONDecodeError:
                return {}
    return {}

def save_data(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

# Initialize orders and customers
orders = load_data(ORDERS_FILE)
customers = load_data(CUSTOMERS_FILE)

@app.route("/")
def home():
    return jsonify({"message": "Welcome to the Pizza Shop API!"})

@app.route("/place_order", methods=["POST"])
def place_order():
    """
    Endpoint to place a new order.
    """
    global orders, customers
    data = request.get_json()

    try:
        customer_name = data["customer_name"]
        phone_number = data["phone_number"]
        order_details = data["order_details"]

        # Generate order ID
        order_id = str(len(orders) + 1).zfill(4)

        # Save order
        orders[order_id] = {
            "customer_name": customer_name,
            "phone_number": phone_number,
            "order_details": order_details,
            "status": "Received",
            "order_time": str(datetime.now()),
        }
        save_data(ORDERS_FILE, orders)

        # Update customer history
        if phone_number in customers:
            customers[phone_number]["order_history"].append(order_id)
        else:
            customers[phone_number] = {
                "name": customer_name,
                "order_history": [order_id]
            }
        save_data(CUSTOMERS_FILE, customers)

        return jsonify({"message": "Order placed successfully!", "order_id": order_id}), 201

    except KeyError as e:
        return jsonify({"error": f"Missing key: {e}"}), 400

@app.route("/get_order/<order_id>", methods=["GET"])
def get_order(order_id):
    """
    Retrieve details of a specific order.
    """
    global orders
    if order_id in orders:
        return jsonify(orders[order_id]), 200
    return jsonify({"error": "Order not found"}), 404

@app.route("/get_customer/<phone_number>", methods=["GET"])
def get_customer(phone_number):
    """
    Retrieve customer details including order history.
    """
    global customers
    if phone_number in customers:
        return jsonify(customers[phone_number]), 200
    return jsonify({"error": "Customer not found"}), 404

@app.route("/suggest_upsell", methods=["POST"])
def suggest_upsell():
    """
    Suggest an upsell item based on the order details.
    """
    try:
        import openai
        openai.api_key = os.getenv("OPENAI_API_KEY")
        data = request.get_json()
        order_details = data["order_details"]

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Suggest a complementary item based on the order. Keep it short."},
                {"role": "user", "content": f"Order details: {order_details}"}
            ],
            max_tokens=50,
            temperature=0.7,
        )
        upsell = response.choices[0].message.content.strip()
        return jsonify({"upsell_suggestion": upsell}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
