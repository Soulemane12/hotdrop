from flask import Flask, request, jsonify
from main import process_message

app = Flask(__name__)

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '')
    assistant_response = process_message(user_message)
    return jsonify({"response": assistant_response})

if __name__ == '__main__':
    app.run(debug=True, port=8000)
