from flask import Flask, request, render_template, url_for, send_file
import os
import my_spacy
from spacy.lang.en.stop_words import STOP_WORDS
from string import punctuation
from heapq import nlargest
from pymongo import MongoClient

app = Flask(__name__, template_folder='templates')

app.config['UPLOAD_FOLDER'] = os.path.join(os.path.expanduser('~'), 'Downloads')  # Set upload folder to Downloads directory

stopwords = list(STOP_WORDS)
nlp = my_spacy.load('en_core_web_sm')

# Connect to MongoDB
client = MongoClient('mongodb://localhost:27017/')  # Replace with your MongoDB connection URL
db = client['keylogger']
collection = db['reports']

@app.route('/')
def hello_world():
    return render_template("nlp.html", message='')

@app.route('/upload', methods=['POST'])
def upload():
    # Retrieve latest report text from MongoDB
    report = collection.find_one({}, sort=[('timestamp', -1)])  # Sort by '_id' field in descending order to get latest report
    if report is None:
        return render_template("nlp.html", message='No report found in MongoDB')
    else:
        text = report['content']  # Updated to retrieve 'content' field from MongoDB

        doc = nlp(text)
        tokens = [token.text for token in doc]
        word_freq = {}
        for word in doc:
            if word.text.lower() not in stopwords and word.text.lower() not in punctuation:
                if word.text not in word_freq.keys():
                    word_freq[word.text] = 1
                else:
                    word_freq[word.text] += 1

        max_freq = max(word_freq.values())
        for word in word_freq.keys():
            word_freq[word] = word_freq[word] / max_freq

        sent_tokens = [sent for sent in doc.sents]
        sent_scores = {}
        for sent in sent_tokens:
            for word in sent:
                if word.text in word_freq.keys():
                    if sent not in sent_scores.keys():
                        sent_scores[sent] = word_freq[word.text]
                    else:
                        sent_scores[sent] += word_freq[word.text]

        select_len = int(len(sent_tokens) * 0.3)

        if len(text.split(' ')) <= 100:  # Check if length of text is 100 or below 100
            summary = text  # Set the summary to the original text
        else:
            summary = nlargest(select_len, sent_scores, key=sent_scores.get)
            final_summary = [word.text for word in summary]
            summary = " ".join(final_summary)

        # Create 'output.txt' file with the summarized text
        output_file = os.path.join(app.config['UPLOAD_FOLDER'], 'output.txt')
        with open(output_file, "w") as f:
            f.write(summary)

        return render_template("nlp.html", message='Summary generated successfully. Click "Download Summary" to download.')

@app.route('/download', methods=['GET'])
def download():
    report = collection.find_one({}, sort=[('timestamp', -1)])  # Sort by '_id' field in descending order to get latest report
    if report is None:
        return render_template("nlp.html", message='No report found in MongoDB')
    else:
        text = report['content']  # Updated to retrieve 'content' field from MongoDB

        doc = nlp(text)
        tokens = [token.text for token in doc]
        word_freq = {}
        for word in doc:
            if word.text.lower() not in stopwords and word.text.lower() not in punctuation:
                if word.text not in word_freq.keys():
                    word_freq[word.text] = 1
                else:
                    word_freq[word.text] += 1

        max_freq = max(word_freq.values())
        for word in word_freq.keys():
            word_freq[word] = word_freq[word] / max_freq

        sent_tokens = [sent for sent in doc.sents]
        sent_scores = {}
        for sent in sent_tokens:
            for word in sent:
                if word.text in word_freq.keys():
                    if sent not in sent_scores.keys():
                        sent_scores[sent] = word_freq[word.text]
                    else:
                        sent_scores[sent] += word_freq[word.text]

        select_len = int(len(sent_tokens) * 0.3)

        if len(text.split(' ')) <= 100:  # Check if length of text is 100 or below 100
            summary = text  # Set the summary to the original text
        else:
            summary = nlargest(select_len, sent_scores, key=sent_scores.get)
            final_summary = [word.text for word in summary]
            summary = " ".join(final_summary)
        
        output_file = os.path.join(app.config['UPLOAD_FOLDER'], 'output.txt')
        with open(output_file, "w") as f:
            f.write(summary)

    
    return send_file(output_file, as_attachment=True)

    
if __name__ == "__main__":
    app.run(debug=True)
