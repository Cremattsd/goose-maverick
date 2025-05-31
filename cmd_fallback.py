from flask import jsonify

def handle_fallback():
    answer = "I’m not sure what you mean! 😅 Try something like 'send realblast', 'predict deal', or 'sync contacts'. What do you want to do?"
    return jsonify({"answer": answer, "tts": answer})
