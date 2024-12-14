import openai
import os
import json
from dotenv import load_dotenv
import uuid
import re
import logging
import datetime

# Configure logging
logging.basicConfig(
    filename='assistant.log',
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s'
)

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

ORDERS_FILE = "orders.json"
CUSTOMERS_FILE = "customers.json"

def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            try:
                data = json.load(file)
                return data
            except json.JSONDecodeError:
                print(f"Warning: {file_path} is empty or contains invalid JSON. Initializing as empty.")
                return {}
    else:
        return {}

def save_data(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

def generate_order_id():
    return str(uuid.uuid4())

def get_valid_phone_number():
    while True:
        phone_number = input("Assistant: Can I get your phone number please?\nYou: ")
        if re.match(r"^\d{10}$", phone_number):
            return phone_number
        else:
            print("Assistant: Please enter a 10-digit phone number without spaces or dashes.")

def get_order_details(initial_input):
    order = {}
    
    # Get pizza size if not specified
    if "large" in initial_input.lower():
        order["size"] = "Large"
    elif "medium" in initial_input.lower():
        order["size"] = "Medium"
    elif "small" in initial_input.lower():
        order["size"] = "Small"
    else:
        print("Assistant: What size would you like? (Small/Medium/Large)")
        order["size"] = input("You: ").capitalize()
    
    # Get toppings
    print("Assistant: What toppings would you like on your pizza?")
    order["toppings"] = input("You: ")
    
    # Get delivery method
    print("Assistant: Is this for pickup or delivery?")
    order["delivery_method"] = input("You: ").lower()
    
    if order["delivery_method"] == "delivery":
        print("Assistant: What's the delivery address?")
        order["address"] = input("You: ")
    
    return {
        "order_time": str(datetime.datetime.now()),
        "pizza": {
            "size": order["size"],
            "toppings": order["toppings"]
        },
        "delivery_method": order["delivery_method"],
        "address": order.get("address", None)
    }

def suggest_upsells(order_details):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Suggest one complementary item based on the order. Keep it short and natural."},
                {"role": "user", "content": f"Order: {order_details}"}
            ],
            max_tokens=50,
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()
    except openai.error.OpenAIError as e:
        logging.error(f"Error suggesting upsells: {e}")
        return ""

def handle_order(phone_number, customer_name, initial_input):
    """Process the order with the given details."""
    global orders
    
    # Get complete order details
    order_details = get_order_details(initial_input)
    
    # Show order summary
    print("\nAssistant: Let me confirm your order:")
    print(f"- {order_details['pizza']['size']} Pizza with {order_details['pizza']['toppings']}")
    print(f"- {order_details['delivery_method'].title()}")
    if order_details['address']:
        print(f"- Delivery to: {order_details['address']}")
    
    # Suggest upsell
    upsell = suggest_upsells(order_details)
    if upsell:
        print(f"\nAssistant: Would you like to add {upsell}?")
        if input("You: ").lower() in ["yes", "y", "sure", "ok"]:
            order_details["extras"] = upsell
            print("Assistant: Added to your order!")
    
    # Final confirmation
    print("\nAssistant: Would you like to place this order?")
    if input("You: ").lower() in ["yes", "y", "sure", "ok"]:
        order_id = generate_order_id()
        orders[order_id] = {
            "customer_name": customer_name,
            "phone_number": phone_number,
            "order_details": order_details,
            "status": "Received"
        }
        save_data(ORDERS_FILE, orders)
        customers[phone_number]["order_history"].append(order_id)
        save_data(CUSTOMERS_FILE, customers)
        print(f"\nAssistant: Great! Your order is confirmed. Your order number is {order_id}")
        if order_details["delivery_method"] == "delivery":
            print("We'll deliver it to you soon!")
        else:
            print("It will be ready for pickup in about 20-25 minutes.")
        
        logging.info(f"Order placed by {customer_name} ({phone_number}): {order_details}")
    else:
        print("Assistant: No problem! Let me know if you'd like to make any changes or try something else.")

def main_conversation():
    print("Assistant: Welcome to our Pizza Shop! How can I help you today?")
    
    # Define global variables
    global orders, customers
    orders = load_data(ORDERS_FILE)
    customers = load_data(CUSTOMERS_FILE)

    while True:
        user_input = input("You: ")

        if user_input.lower() in ["exit", "quit", "bye"]:
            print("Assistant: Thanks for visiting! Have a great day!")
            break
            
        if "pizza" in user_input.lower() or "order" in user_input.lower():
            # Get customer details
            phone_number = get_valid_phone_number()
            
            if phone_number in customers:
                name = customers[phone_number]["name"]
                print(f"Assistant: Welcome back, {name}!")
            else:
                print("Assistant: First time ordering with us?")
                name = input("What's your name? ")
                customers[phone_number] = {"name": name, "order_history": []}
                save_data(CUSTOMERS_FILE, customers)
                print(f"Assistant: Nice to meet you, {name}!")
            
            # Handle the order
            handle_order(phone_number, name, user_input)
        else:
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a helpful pizza shop assistant."},
                        {"role": "user", "content": user_input}
                    ],
                    max_tokens=150,
                    temperature=0.7,
                )
                print(f"Assistant: {response.choices[0].message.content.strip()}")
            except openai.error.OpenAIError as e:
                print("Assistant: I'm sorry, I'm having trouble understanding. Could you try asking that another way?")
                logging.error(f"Error handling inquiry: {e}")

if __name__ == "__main__":
    main_conversation()