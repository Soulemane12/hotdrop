import openai
import os
import json
from dotenv import load_dotenv
import re
import logging
import datetime
from textblob import TextBlob
import threading
from enum import Enum, auto

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

TIMEOUT_DURATION = 300

class ConversationState(Enum):
    GREETING = auto()
    ASK_PHONE = auto()
    CHECK_CUSTOMER = auto()
    ASK_NAME = auto()
    COLLECTING_ORDER = auto()
    ASK_EXTRAS_FOR_PIZZA = auto()
    ASK_BEVERAGES = auto()
    ASK_ADDITIONAL_EXTRAS = auto()
    ASK_DELIVERY_METHOD = auto()
    ASK_ADDRESS = auto()
    ASK_PAYMENT = auto()
    CONFIRM_ORDER = auto()
    END = auto()
    ASK_TOPPINGS = auto()

class ConversationTimer:
    def __init__(self, timeout, callback):
        self.timeout = timeout
        self.callback = callback
        self.timer = threading.Timer(self.timeout, self.callback)

    def reset(self):
        self.timer.cancel()
        self.timer = threading.Timer(self.timeout, self.callback)
        self.timer.start()

    def cancel(self):
        self.timer.cancel()

def on_timeout():
    logging.info("Conversation timed out due to inactivity.")

def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            try:
                data = json.load(file)
                return data
            except json.JSONDecodeError:
                logging.warning(f"{file_path} is empty or invalid. Initializing empty data.")
                return {}
    else:
        return {}

def save_data(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

def generate_order_id(orders):
    with ORDER_ID_LOCK:
        if not os.path.exists(ORDER_ID_FILE):
            with open(ORDER_ID_FILE, "w") as f:
                f.write("0000")

        with open(ORDER_ID_FILE, "r") as f:
            last_id_str = f.read().strip()
            try:
                last_id = int(last_id_str)
            except ValueError:
                logging.error(f"Invalid order ID in {ORDER_ID_FILE}. Resetting to 0000.")
                last_id = 0

        new_id = last_id + 1

        if new_id > 9999:
            logging.error("Order ID exceeded 9999. Resetting to 0001.")
            new_id = 1  
        new_id_str = f"{new_id:04d}"

        if new_id_str in orders:
            logging.error(f"Order ID {new_id_str} already exists. Incrementing to find a unique ID.")
            while new_id_str in orders and new_id <= 9999:
                new_id += 1
                if new_id > 9999:
                    new_id = 1
                new_id_str = f"{new_id:04d}"
            if new_id_str in orders:
                logging.critical("All order IDs from 0001 to 9999 are in use. Cannot generate a new order ID.")
                raise Exception("Order ID limit reached.")

        with open(ORDER_ID_FILE, "w") as f:
            f.write(new_id_str)

    return new_id_str

def is_negative_sentiment(user_input):
    analysis = TextBlob(user_input)
    return analysis.sentiment.polarity < -0.5

def should_end_conversation(user_input):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Determine if the user intends to end the conversation. Respond with 'yes' or 'no'."},
                {"role": "user", "content": user_input}
            ],
            max_tokens=3,
            temperature=0
        )
        decision = response.choices[0].message.content.strip().lower()
        return decision == "yes"
    except openai.error.OpenAIError as e:
        logging.error(f"Error in intent detection: {e}")
        return False

def suggest_upsells(order_details):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Suggest one complementary item based on the order. Keep it short and natural."},
                {"role": "user", "content": f"Order details: {order_details}"}
            ],
            max_tokens=50,
            temperature=0.5,
        )
        upsell = response.choices[0].message.content.strip()
        return upsell
    except openai.error.OpenAIError as e:
        logging.error(f"Error suggesting upsells: {e}")
        return ""

orders = load_data(ORDERS_FILE)
customers = load_data(CUSTOMERS_FILE)

session_data = {
    "state": ConversationState.GREETING,
    "phone_number": None,
    "customer_name": None,
    "order_details": {
        "pizzas": [],
        "beverages": [],
        "extras": [],
        "delivery_method": None,
        "address": None,
        "payment_method": None,
        "order_time": None
    },
    "awaiting_pizza_details": False,
    "awaiting_extras_for_pizza": False,
    "awaiting_beverages": False,
    "awaiting_delivery_method": False,
    "awaiting_address": False,
    "awaiting_payment": False,
    "awaiting_confirmation": False
}

def start_conversation():
    global session_data
    session_data = reset_session_data()  # Reset session data to start fresh
    return "Welcome to SliceSync! Can I get your phone number, please? (10 digits)"

def process_message(user_input):
    global session_data, orders, customers

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": """You are a friendly pizza restaurant assistant. Guide the conversation to collect:
                    1. Phone number (must be 10 digits)
                    2. Name (if new customer)
                    3. Pizza orders (size, toppings, quantity)
                    4. Extra toppings or modifications
                    5. Beverages
                    6. Side orders
                    7. Delivery/pickup preference
                    8. Address (if delivery)
                    9. Payment method
                    
                    Available menu:
                    - Pizza sizes: Small, Medium, Large
                    - Toppings: Pepperoni, Mushrooms, Onions, Sausage, Extra Cheese
                    - Beverages: Coke, Sprite, Diet Coke
                    - Sides: Garlic Bread, Wings, Salads
                    
                    Current state: """ + str(session_data["state"]) + 
                    "\nCurrent order details: " + str(session_data["order_details"]) +
                    "\nCustomer info: " + str({"name": session_data["customer_name"], "phone": session_data["phone_number"]})},
                {"role": "assistant", "content": "Let me help with your pizza order!"},
                {"role": "user", "content": user_input}
            ],
            temperature=0.7
        )
        ai_response = response.choices[0].message.content

        # Process the response based on the current state
        if session_data["state"] == ConversationState.GREETING:
            session_data["state"] = ConversationState.ASK_PHONE
            return "Welcome to SliceSync! To get started, could you please share your phone number? (10 digits)"

        if session_data["state"] == ConversationState.ASK_PHONE:
            if re.match(r"^\d{10}$", user_input.strip()):
                session_data["phone_number"] = user_input.strip()
                if session_data["phone_number"] in customers:
                    session_data["customer_name"] = customers[session_data["phone_number"]]["name"]
                    session_data["state"] = ConversationState.COLLECTING_ORDER
                    return f"Welcome back {session_data['customer_name']}! " + ai_response
                else:
                    session_data["state"] = ConversationState.ASK_NAME
                    return "I see you're new here! What's your name?"
            else:
                return "I need a valid 10-digit phone number. Could you please provide that?"

        if session_data["state"] == ConversationState.ASK_NAME:
            session_data["customer_name"] = user_input.strip()
            customers[session_data["phone_number"]] = {"name": session_data["customer_name"], "order_history": []}
            save_data(CUSTOMERS_FILE, customers)
            session_data["state"] = ConversationState.COLLECTING_ORDER
            return ai_response

        if session_data["state"] == ConversationState.COLLECTING_ORDER:
            # Let AI handle the order collection process
            pizza_info = extract_pizza_info(ai_response)
            if pizza_info:
                session_data["order_details"]["pizzas"].append(pizza_info)
                session_data["state"] = ConversationState.ASK_EXTRAS_FOR_PIZZA
            return ai_response

        if session_data["state"] == ConversationState.ASK_EXTRAS_FOR_PIZZA:
            if "no" not in user_input.lower():
                extras = extract_extras(ai_response)
                if extras:
                    session_data["order_details"]["pizzas"][-1]["extras"] = extras
            session_data["state"] = ConversationState.ASK_BEVERAGES
            return ai_response

        # Continue with similar pattern for other states...

        if session_data["state"] == ConversationState.CONFIRM_ORDER:
            if "yes" in user_input.lower():
                # Process order confirmation
                order_id = generate_order_id(orders)
                session_data["order_details"]["order_time"] = str(datetime.datetime.now())
                orders[order_id] = {
                    "customer_name": session_data["customer_name"],
                    "phone_number": session_data["phone_number"],
                    "order_details": session_data["order_details"],
                    "status": "Received"
                }
                save_data(ORDERS_FILE, orders)
                customers[session_data["phone_number"]]["order_history"].append(order_id)
                save_data(CUSTOMERS_FILE, customers)
                
                return f"Great! Your order #{order_id} has been confirmed. " + ai_response
            else:
                session_data["state"] = ConversationState.COLLECTING_ORDER
                return "Let's modify your order. " + ai_response

        return ai_response

    except openai.error.OpenAIError as e:
        logging.error(f"OpenAI API error: {e}")
        return "I'm having trouble processing your request. Could you please try again?"

def extract_pizza_info(ai_response):
    # Add logic to extract pizza information from AI response
    # Return dictionary with size, toppings, quantity
    pass

def extract_extras(ai_response):
    # Add logic to extract extras from AI response
    # Return list of extras
    pass

def reset_session_data():
    return {
        "state": ConversationState.GREETING,
        "phone_number": None,
        "customer_name": None,
        "order_details": {
            "pizzas": [],
            "beverages": [],
            "extras": [],
            "delivery_method": None,
            "address": None,
            "payment_method": None,
            "order_time": None
        },
        "awaiting_pizza_details": False,
        "awaiting_extras_for_pizza": False,
        "awaiting_beverages": False,
        "awaiting_delivery_method": False,
        "awaiting_address": False,
        "awaiting_payment": False,
        "awaiting_confirmation": False
    }
