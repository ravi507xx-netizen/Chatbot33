from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/prompt/<text>", methods=["GET"])
def chatbot(text):
    # Simple logic — replace this with AI/LLM API later
    response = f"You said: {text}"
    return jsonify({"response": response})

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Chatbot API is running. Use /prompt/{text}"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
