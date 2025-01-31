import os
import re
import csv
import cv2
import json
import math
import time
import pickle
import cvzone
import shutil
import face_recognition
from flask import Flask, render_template, request, Response
from flask import redirect, url_for, jsonify
from flask_cors import CORS
from ultralytics import YOLO
from werkzeug.utils import secure_filename
from sklearn import neighbors
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings("ignore")

UPLOAD_FOLDER = r'public/images'  # Change this to the desired upload folder
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

app = Flask(__name__)
CORS(app)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
webcam = None
global_selected_class = None
global_selected_batch = None
isReal = False
studentsData = {}
liveConfidence = 0.4

def train_from_uploaded_images(upload_folder, model_save_path):
    X = []
    y = []

    for class_dir in os.listdir(upload_folder):
        if not os.path.isdir(os.path.join(upload_folder, class_dir)):
            continue

        for img_path in image_files_in_folder(os.path.join(upload_folder, class_dir)):
            image = face_recognition.load_image_file(img_path)
            face_bounding_boxes = face_recognition.face_locations(image)

            if len(face_bounding_boxes) != 1:
                continue

            face_encoding = face_recognition.face_encodings(image, known_face_locations=face_bounding_boxes)[0]

            if len(face_encoding) > 0:
                flattened_face_encoding = np.array(face_encoding).flatten()
                X.append(flattened_face_encoding)
                y.append(class_dir)

    if len(X) > 0:
        # Choose a value of n_neighbors that is less than or equal to the number of samples
        n_neighbors = min(int(round(math.sqrt(len(X)))), len(X))
        knn_clf = neighbors.KNeighborsClassifier(n_neighbors=n_neighbors, algorithm='ball_tree', weights='distance')
        knn_clf.fit(X, y)

        if model_save_path is not None:
            with open(model_save_path, 'wb') as f:
                pickle.dump(knn_clf, f)
            print("Training complete")
        return knn_clf
    else:
        print("No valid face encodings found for training.")
        return None

def train(train_dir, model_save_path, n_neighbors=2, knn_algo='ball_tree', verbose=False):
    X = []
    y = []
    # Loop through each person in the training set
    for class_dir in os.listdir(train_dir):
        if not os.path.isdir(os.path.join(train_dir, class_dir)):
            continue
        # Loop through each training image for the current person
        for img_path in image_files_in_folder(os.path.join(train_dir, class_dir)):
            image = face_recognition.load_image_file(img_path)
            face_bounding_boxes = face_recognition.face_locations(image)
            print("processing:", img_path)
            if len(face_bounding_boxes) != 1:
                # If there are no people (or too many people) in a training image, skip the image.
                if verbose:
                    print("Image {} not suitable for training: {}".format(img_path, "Didn't find a face" if len(face_bounding_boxes) < 1 else "Found more than one face"))
            else:
                # Add face encoding for the current image to the training set
                face_encoding = face_recognition.face_encodings(image, known_face_locations=face_bounding_boxes)[0]
                # Check if the face encoding is valid
                if len(face_encoding) > 0:
                    # Reshape to 1D array
                    flattened_face_encoding = np.array(face_encoding).flatten()
                    X.append(flattened_face_encoding)
                    y.append(class_dir)

    # Check if there are valid samples in X before fitting the classifier
    if len(X) > 0:
        # Determine how many neighbors to use for weighting in the KNN classifier
        if n_neighbors is None or n_neighbors > len(X):
            # n_neighbors = int(round(math.sqrt(len(X))))
            n_neighbors = min(10, len(X))
            if verbose:
                print("Chose n_neighbors automatically:", n_neighbors)
        # Create and train the KNN classifier
        knn_clf = neighbors.KNeighborsClassifier(n_neighbors=n_neighbors, algorithm=knn_algo, weights='distance')
        knn_clf.fit(X, y)
        # Save the trained KNN classifier
        if model_save_path is not None:
            with open(model_save_path, 'wb') as f:
                pickle.dump(knn_clf, f)
            print("Training complete")
        return knn_clf
    else:
        print("No valid face encodings found for training.")
        return None


def image_files_in_folder(folder):
    return [os.path.join(folder, f) for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    

# Function to save an uploaded file with a unique name in its subfolder
def save_uploaded_file(file, upload_folder, filename):
    # Generate a unique subfolder name based on the filename without extension
    folder_name = os.path.splitext(filename)[0]
    subfolder_path = os.path.join(upload_folder, folder_name)

    # Generate a unique filename if a file with the same name exists
    count = 1
    while os.path.exists(os.path.join(subfolder_path, filename)):
        count += 1
        filename_without_ext, file_extension = os.path.splitext(filename)
        filename = f"{filename_without_ext}{count}{file_extension}"

    # Create the subfolder if it doesn't exist
    os.makedirs(subfolder_path, exist_ok=True)

    # Save the file with the unique name inside the subfolder
    file.save(os.path.join(subfolder_path, filename))

def find_camera_index():
    # Try opening cameras from index 0 onwards
    index = 0
    while True:
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            cap.release()
            index += 1
            if index >= 10:  
                return None  # No camera found within the specified range
        else:
            cap.release()
            return index


def takeAttendance(name, isReal):
    csv_path = '../data/attendance.csv'

    if isReal:
    
        with open(csv_path, 'a+') as f:
            f.seek(0)
            lines = f.readlines()
            nameList = [line.split(',')[0] for line in lines]
            
            now = datetime.now()
            datestring = now.strftime('%H:%M:%S')
            
            if name not in nameList:
                f.write(f'{name},{datestring},,\n')
            else:
                # Update the existing entry with outtime and duration
                for line in lines:
                    if line.startswith(name):
                        # Extract intime
                        intime = line.split(',')[1]
                        # Calculate duration
                        intime_dt = datetime.strptime(intime, '%H:%M:%S')
                        outtime_dt = now
                        duration = outtime_dt - intime_dt
                        # print(str(duration).split(',')[1])

                        duration_str = str(duration).split(',')[1].split('.')[0].strip()  # Convert to string in right format

                        updated_line = f'{name},{intime},{now.strftime("%H:%M:%S")},{duration_str}\n'
                        lines[lines.index(line)] = updated_line
                        break
                
                # Write the updated content back to the file
                f.seek(0)
                f.truncate()
                f.writelines(lines)
                
        # Create JSON file with the updated data
        jsonAttendanceData = []
        with open(csv_path) as csvFile:
            csvReader = csv.reader(csvFile)
            for row in csvReader:
                jsonAttendanceData.append({
                    'name': row[0],
                    'intime': row[1],
                    'outtime': row[2],
                    'duration': row[3]
                })

        with open('../data/attendance.json', 'w') as jsonFile:
            jsonFile.write(json.dumps(jsonAttendanceData, indent=4))


def predict(img, knn_clf=None, model_path=None, threshold=0.5):
    if knn_clf is None and model_path is None:
        raise Exception("Must supply knn classifier either through knn_clf or model_path")
    # Load a trained KNN model (if one was passed in)
    if knn_clf is None:
        with open(model_path, 'rb') as f:
            knn_clf = pickle.load(f)
    # Load image file and find face locations
    img = img
    face_boxes = face_recognition.face_locations(img)
    # If no faces are found in the image, return an empty result.
    if len(face_boxes) == 0:
        return []
    # Find encodings for faces in the test image
    faces_encodings = face_recognition.face_encodings(img, known_face_locations=face_boxes)
    
    predictions = []
    
    for face_encoding, face_box in zip(faces_encodings, face_boxes):
        # Use the KNN model to find the best match for each face
        closest_distances = knn_clf.kneighbors([face_encoding], n_neighbors=1)
        is_match = closest_distances[0][0][0] <= threshold
        
        if is_match:
            name = knn_clf.predict([face_encoding])[0]
        else:
            name = "unknown"
        
        predictions.append((name, face_box))
    
    return predictions


def gen():
    global webcam, global_selected_class, global_selected_batch, studentsData, isReal

    selected_class = global_selected_class
    selected_batch = global_selected_batch

    with open("../data/students.js") as jsFile:
        jsCode = jsFile.read()

    # Use a regular expression to extract the relevant data
    match = re.search(r'const studentsData = (\[.*?\]);', jsCode, re.DOTALL)

    if match:
        # Convert the string to a list of dictionaries
        students_data_json = match.group(1)
        studentsData = eval(students_data_json)  # Evaluate the JSON-like string
    else:
        studentsData = {}

    for class_data in studentsData:
        if selected_class in class_data:
            batch_data = class_data[selected_class].get(selected_batch)
            if batch_data:
                matching_data = batch_data
                break

    studentsData = matching_data

    print(list(studentsData.keys()))

    if webcam is None:
        webcam = cv2.VideoCapture(find_camera_index())

    liveModel = YOLO("../../public/classifier/version3_best.pt")
    classNames = ["fake", "real"]
    isReal_confidence_threshold = 0.99  # You can adjust this threshold based on your requirements
    history_length = 15  # Number of frames to consider for temporal consistency
    confidence_history = []  # List to store confidence levels over the last frames

    while 1==1:
        try:

            rval, frame = webcam.read()

            liveResults = liveModel(frame, stream=True, verbose=False)

            for r in liveResults:
                boxes = r.boxes
                real_count = 0
                fake_count = 0

                for box in boxes:

                    conf = math.ceil((box.conf[0] * 100)) / 100
                    cls = int(box.cls[0])

                    if conf > liveConfidence:
                        if classNames[cls] == 'real':
                            print("real")
                            real_count += 1 
                        else:
                            print("fake")
                            # name = name + " Fake"
                            fake_count += 1
                            # continue
            
            total_faces = real_count + fake_count
            confidence_index = real_count / total_faces if total_faces > 0 else 0
            confidence_history.append(confidence_index)

            # Keep history length consistent
            if len(confidence_history) > history_length:
                confidence_history.pop(0)

            # Decide isReal based on temporal consistency
            avg_confidence = sum(confidence_history) / len(confidence_history) if confidence_history else 0
            if avg_confidence >= isReal_confidence_threshold:
                isReal = True
            else:
                isReal = False


            if not rval:
                print("Error reading frame. Restarting webcam...")
                webcam.release() 
                time.sleep(1)  
                webcam = cv2.VideoCapture(find_camera_index())
                continue

            frame = cv2.flip(frame, 1)
            frame_copy = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
            frame_copy = cv2.cvtColor(frame_copy, cv2.COLOR_BGR2RGB)

            # Perform predictions using the classifier
            predictions = predict(frame_copy, model_path="../../public/classifier/trained_knn_model.clf")  # Update path
            font = cv2.FONT_HERSHEY_DUPLEX
            
            for name, (top, right, bottom, left) in predictions:
                top *= 4  # scale back the frame since it was scaled to 1/4 in size
                right *= 4
                bottom *= 4
                left *= 4

                cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 255), 2)
                cv2.putText(frame, name, (left - 10, top - 6), font, 2.5, (255, 255, 255), 2)

                if name != 'unknown' and name in list(studentsData.keys()):
                    takeAttendance(name, isReal)

            ret, jpeg = cv2.imencode('.jpg', frame)
            frame_encoded = jpeg.tobytes()
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_encoded + b'\r\n')

        except Exception as e:
            print('Error:', e)
            webcam.release()
            webcam = None
            continue
        
        # rval, frame = webcam.read()

    # webcam.release()
    cv2.destroyAllWindows()


@app.route('/upload', methods=['POST'])
def upload_files():
    uploaded_files = request.files.getlist('file')  # Get a list of uploaded files

    if len(uploaded_files) == 0:
        return jsonify({'error': 'No files provided'})

    uploaded_filenames = []

    for file in uploaded_files:
        if file.filename == '':
            continue  

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            save_uploaded_file(file, app.config['UPLOAD_FOLDER'], filename)
            uploaded_filenames.append(filename)

    if uploaded_filenames:
        train("public/images/", "../../public/classifier/trained_knn_model.clf")

        # Optionally, you can return a response with the list of successfully uploaded filenames
        return jsonify({'success': 'Files uploaded and trained successfully', 'uploaded_files': uploaded_filenames})
    else:
        return jsonify({'error': 'No valid files uploaded'})


@app.route('/predict', methods=['POST'])
def predict_image():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'})

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'Empty filename'})

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        img_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        img = cv2.imread(img_path)
        predictions = predict(img, model_path="classifier/trained_knn_model.clf")  
        # Process predictions as needed
        for name, (top, right, bottom, left) in predictions:
            takeAttendance(name)  # Call the takeAttendance function here
        return jsonify({'predictions': result})
    else:
        return jsonify({'error': 'Invalid file format'})


@app.route('/submit-attendance', methods=['POST'])
def submit_attendance():
    try:
        archive_folder = '../data/archive/'
        current_date = datetime.now().strftime('%Y-%m-%d')
        save_time = datetime.now().strftime('%H-%M-%S')

        shutil.move('../data/attendance.csv', f'{archive_folder}attendance_{current_date}_{save_time}.csv')
        shutil.move('../data/attendance.json', f'{archive_folder}attendance_{current_date}_{save_time}.json')

        # Clear current csv file
        open('../data/attendance.csv', 'w').close()

        # Overwrite the JSON file with an empty array
        with open('../data/attendance.json', 'w') as jsonFile:
            jsonFile.write("[]")

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# @app.route('/success', methods=['GET', 'POST'])
# def success():
#     if 'file' not in request.files:
#         return render_template('upload.html')
#     file = request.files['file']
#     if file.filename == '':
#         return render_template('upload.html')
#     if file and allowed_file(file.filename):
#         filename = secure_filename(file.filename)
#         save_uploaded_file(file, app.config['UPLOAD_FOLDER'], filename)
#         train("public/images/", "public/classifier/trained_knn_model.clf")
#         return render_template('upload.html')
#     else:
#         return render_template('upload.html')


@app.route('/release_webcam')
def release_webcam():
    global webcam
    if webcam is not None:
        webcam.release()
        cv2.destroyAllWindows()
        webcam = None  # Reset the webcam variable
        return jsonify({'success': True})
    else:
        return 'Webcam is not currently active'


@app.route('/video_feed')
def video_feed():
    global global_selected_class, global_selected_batch

    # Retrieve selectedClass and selectedBatch from the request
    global_selected_class = request.args.get('class')
    global_selected_batch = request.args.get('batch')

    return Response(gen(), mimetype='multipart/x-mixed-replace; boundary=frame')

# @app.route('/train_classifier', methods=['GET', 'POST'])
# def train_classifier():
#     train_from_uploaded_images(app.config['UPLOAD_FOLDER'], 'public/classifier/trained_knn_model.clf')
#     return redirect(url_for('upload_file'))

if __name__ == "__main__":
    app.run(debug=True)
