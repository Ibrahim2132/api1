import os
import json
import sys
from datetime import datetime, timedelta
import uuid
import io # <-- لإدارة البايتات
import hashlib # <-- لحساب الهاش

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv # <-- لتحميل متغيرات البيئة
from PIL import Image # <-- لمعالجة الصور
import google.generativeai as genai # <-- مكتبة Gemini

# --- Load Environment Variables ---
load_dotenv()
print("Attempting to load environment variables...") # Debug print

# --- تحديد المسارات ---
persistent_data_dir = '/tmp' # أو المسار المناسب لبيئتك
db_path = os.path.join(persistent_data_dir, 'databases4.db')
UPLOAD_FOLDER = os.path.join(persistent_data_dir, 'uploads')
db_dir = os.path.dirname(db_path) # مجلد قاعدة البيانات

# --- التأكد من وجود المجلدات الضرورية قبل إعداد التطبيق ---
try:
    print(f"Ensuring directory exists: {db_dir}")
    os.makedirs(db_dir, exist_ok=True)
    print(f"Ensuring directory exists: {UPLOAD_FOLDER}")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    print("Required directories checked/created.")
except OSError as e:
    print(f"FATAL ERROR: Could not create necessary directories at {persistent_data_dir}. Check permissions/mount point. Error: {e}")
    sys.exit(f"Directory creation failed: {e}")

# --- إعداد التطبيق و SQLAlchemy ---
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ضع-مفتاح-سري-قوي-هنا-للانتاج')
if app.config['SECRET_KEY'] == 'ضع-مفتاح-سري-قوي-هنا-للانتاج' and os.environ.get('FLASK_ENV') != 'development':
     print("WARNING: Using default SECRET_KEY in a non-development environment!")

db = SQLAlchemy(app)

# --- Configure Gemini API ---
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
gemini_model = None

if not GOOGLE_API_KEY:
    print("ERROR: GOOGLE_API_KEY not found in environment variables (.env file). Image analysis will be disabled.")
else:
    try:
        print("Configuring Gemini API...")
        genai.configure(api_key=GOOGLE_API_KEY)
        gemini_model = genai.GenerativeModel('gemini-2.0-flash') # تم التغيير إلى فلاش الأحدث
        print("Gemini Model configured successfully.")
    except Exception as e:
        print(f"ERROR configuring Gemini API: {e}. Image analysis will be disabled.")
        gemini_model = None

# --- Define the Fixed Prompts for Gemini ---
LIKE_DETECTION_PROMPT = """Analyze this social media screenshot, paying close attention to platforms like TikTok.
Focus ONLY on the primary like button/icon (e.g., a heart on TikTok/Instagram, a thumb-up on Facebook/YouTube) associated with the main post content.
Determine if this like button is in an 'activated', 'pressed', or 'liked' state.
A 'liked' state is typically indicated by a VISUAL CHANGE:
- For a heart icon (common on TikTok): It should be FILLED (often with red or another distinct color), not just an outline. An unliked heart is usually an outline or greyed out.
- For a thumb-up icon: It might be FILLED (e.g., blue), highlighted, or have a distinct color change compared to its unliked state (which is often an outline or greyed out).

Respond with ONLY the single digit '1' if the like button clearly appears to be in this 'liked'/'activated'/'pressed' state.
Respond with ONLY the single digit '0' if the like button clearly appears to be in an *unliked*/*inactive*/*unpressed* state (e.g., an outline, not filled, greyed out).
Do not provide any other text, explanation, or formatting."""

COMMENT_DETECTION_PROMPT = """Analyze this social media screenshot (like TikTok, Instagram, Facebook). Search the visible comments section carefully for any comment posted by the username '{username}'. Pay close attention to the username associated with each comment. Respond with ONLY the single digit '1' if a comment clearly posted by the exact username '{username}' is visible in the screenshot. Respond with ONLY the single digit '0' if no comment by this exact username is clearly visible. Do not provide any other text, explanation, or formatting."""
SHARE_DETECTION_PROMPT = """Analyze this social media screenshot (like TikTok, Instagram, Facebook). Focus ONLY on the share button/icon (e.g., arrow, paper plane) or any text indicating a share action related to the main post. Determine if the post appears to have been shared by the user who took the screenshot (look for a highlighted or altered share icon, or text like 'Shared'). Respond with ONLY the single digit '1' if the post appears to have been shared. Respond with ONLY the single digit '0' if the post does not appear to have been shared. Do not provide any other text, explanation, or formatting."""
SUBSCRIBE_DETECTION_PROMPT = """Analyze this social media screenshot (e.g., YouTube, Twitch, etc.). Focus ONLY on the primary subscribe button/icon or text indicating subscription status to the channel/creator featured in the screenshot. Determine if the user who took the screenshot appears to be subscribed to this channel/creator (look for a button that says 'Subscribed', 'Unsubscribe', a highlighted bell icon next to a subscribe button, or similar indicators of an active subscription). Respond with ONLY the single digit '1' if the user appears to be subscribed. Respond with ONLY the single digit '0' if the user appears to be *not* subscribed (e.g., button says 'Subscribe'). Do not provide any other text, explanation, or formatting."""

# --- Storage for Processed Image Hashes (In-Memory) ---
# !!! هام: هذا الـ Set سيفقد محتوياته عند إعادة تشغيل السيرفر !!!
# للحل الدائم، استخدم قاعدة بيانات. سيخزن الآن أزواجًا: (user_id, image_hash)
processed_image_hashes = set()
print(f"Initialized empty set for processed_image_hashes (user_id, image_hash). Size: {len(processed_image_hashes)}")


# --- تعريف موديل المستخدم (User Model) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone_number = db.Column(db.String(20), nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    interests = db.Column(db.Text, nullable=True)
    coins = db.Column(db.Integer, nullable=False, default=0)
    referrer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    referred_by_me_ids = db.Column(db.Text, nullable=True)
    last_spin_time = db.Column(db.DateTime, nullable=True)
    advertisements = db.relationship('Advertisement', backref='advertiser', lazy=True, order_by="Advertisement.created_at.desc()")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def set_interests(self, interests_list):
        if interests_list and isinstance(interests_list, list):
            if all(isinstance(item, str) for item in interests_list):
                self.interests = json.dumps(interests_list)
            else:
                app.logger.warning(f"User {self.id}: Interests list contains non-string elements. Setting interests to null.")
                self.interests = None
        else:
            self.interests = None if interests_list is None else json.dumps([])

    def get_interests(self):
        if self.interests:
            try:
                interests = json.loads(self.interests)
                return interests if isinstance(interests, list) else []
            except json.JSONDecodeError:
                app.logger.error(f"User {self.id}: Failed to decode interests JSON: {self.interests}")
                return []
        return []

    def set_referred_by_me_ids(self, id_list):
        if id_list and isinstance(id_list, list):
            if all(isinstance(item, int) for item in id_list):
                self.referred_by_me_ids = json.dumps(id_list)
            else:
                app.logger.warning(f"User {self.id}: referred_by_me_ids list contains non-integer elements. Setting to empty list.")
                self.referred_by_me_ids = json.dumps([])
        else:
            self.referred_by_me_ids = json.dumps([])

    def get_referred_by_me_ids(self):
        if self.referred_by_me_ids:
            try:
                ids = json.loads(self.referred_by_me_ids)
                return ids if isinstance(ids, list) else []
            except json.JSONDecodeError:
                app.logger.error(f"User {self.id}: Failed to decode referred_by_me_ids JSON: {self.referred_by_me_ids}")
                return []
        return []

    def to_dict(self, include_ads=False):
        referrer_info = {"id": self.referrer_id} if self.referrer_id else None
        user_data = {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone_number": self.phone_number,
            "interests": self.get_interests(),
            "coins": self.coins,
            "referrer": referrer_info,
            "referred_by_me": self.get_referred_by_me_ids(),
            "last_spin_time": self.last_spin_time.isoformat() if self.last_spin_time else None
        }
        if include_ads:
            user_data["advertisements"] = [ad.to_dict() for ad in self.advertisements]
        return user_data

    def __repr__(self):
        return f'<User {self.id} - {self.name} ({self.email}) - Coins: {self.coins}>'


# --- موديل الإعلانات (Advertisement Model) ---
# --- موديل الإعلانات (Advertisement Model) ---
class Advertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True) # صاحب الإعلان
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    link = db.Column(db.Text, nullable=False)
    interests = db.Column(db.Text, nullable=True)
    number_of_clicks = db.Column(db.Integer, nullable=False, default=0)
    coin_per_click = db.Column(db.Integer, nullable=False)
    category = db.Column(db.String(80), nullable=True, index=True)
    subcategory = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_approved = db.Column(db.Boolean, nullable=False, default=False, index=True)
    # --- الإضافة الجديدة ---
    clicked_by_user_ids = db.Column(db.Text, nullable=True) # سيخزن قائمة IDs كـ JSON

    def set_interests(self, interests_list):
        if interests_list and isinstance(interests_list, list):
            if all(isinstance(item, str) for item in interests_list):
                self.interests = json.dumps(interests_list)
            else:
                app.logger.warning(f"Ad {self.id}: Interests list contains non-string elements. Setting interests to null.")
                self.interests = None
        else:
            self.interests = None if interests_list is None else json.dumps([])

    def get_interests(self):
        if self.interests:
            try:
                interests = json.loads(self.interests)
                return interests if isinstance(interests, list) else []
            except json.JSONDecodeError:
                app.logger.error(f"Ad {self.id}: Failed to decode interests JSON: {self.interests}")
                return []
        return []

    # --- الدوال الجديدة لـ clicked_by_user_ids ---
    def set_clicked_by_user_ids(self, id_list):
        if id_list and isinstance(id_list, list):
            if all(isinstance(item, int) for item in id_list):
                self.clicked_by_user_ids = json.dumps(id_list)
            else:
                app.logger.warning(f"Ad {self.id}: clicked_by_user_ids list contains non-integer elements. Setting to empty list.")
                self.clicked_by_user_ids = json.dumps([])
        else:
            self.clicked_by_user_ids = json.dumps([]) # الافتراضي قائمة فارغة

    def get_clicked_by_user_ids(self):
        if self.clicked_by_user_ids:
            try:
                ids = json.loads(self.clicked_by_user_ids)
                return ids if isinstance(ids, list) else []
            except json.JSONDecodeError:
                app.logger.error(f"Ad {self.id}: Failed to decode clicked_by_user_ids JSON: {self.clicked_by_user_ids}")
                return []
        return []

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id, # صاحب الإعلان
            "title": self.title,
            "description": self.description,
            "link": self.link,
            "interests": self.get_interests(),
            "number_of_clicks": self.number_of_clicks,
            "coin_per_click": self.coin_per_click,
            "category": self.category,
            "subcategory": self.subcategory,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "is_active": self.is_active,
            "is_approved": self.is_approved,
            "clicked_by_user_ids": self.get_clicked_by_user_ids() # إضافة الحقل الجديد
        }

    def __repr__(self):
        return f'<Advertisement {self.id} - {self.title} by User {self.user_id}>'

# --- تهيئة قاعدة البيانات ---
try:
    with app.app_context():
        print(f"Initializing database tables at: {db_path}...")
        db.create_all()
        print("Database tables checked/created successfully.")
except Exception as e:
    print(f"FATAL ERROR during initial db.create_all(): {e}")
    sys.exit(f"Database initialization failed: {e}")

# --- دوال مساعدة وامتدادات مسموحة ---
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- نقاط النهاية (API Endpoints) ---

# --- START: Helper function to get user_id and validate user ---
def get_validated_user_from_form(form_data):
    """
    Helper function to get user_id from form data, validate it,
    and return the User object or an error response.
    """
    if 'user_id' not in form_data:
        app.logger.warning("Missing 'user_id' in form data.")
        return None, (jsonify({"error": "Missing 'user_id' form field in the request."}), 400)
    user_id_str = form_data.get('user_id')
    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        app.logger.warning(f"Invalid user_id format: {user_id_str}")
        return None, (jsonify({"error": "'user_id' must be a valid integer."}), 400)

    user = User.query.get(user_id)
    if not user:
        app.logger.warning(f"User with ID {user_id} not found.")
        return None, (jsonify({"error": f"User with ID {user_id} not found."}), 404)
    return user, None
# --- END: Helper function ---

@app.route('/register', methods=['POST'])
def register():
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    phone_number = data.get('phone_number')
    interests_list = data.get('interests')
    referrer_id_from_request = data.get('referrer_id')
    missing_fields = []
    if not name: missing_fields.append('name')
    if not email: missing_fields.append('email')
    if not password: missing_fields.append('password')
    if not phone_number: missing_fields.append('phone_number')
    if missing_fields: return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400
    if User.query.filter_by(email=email).first(): return jsonify({"error": "Email address already registered"}), 409
    if interests_list is not None and not isinstance(interests_list, list): return jsonify({"error": "Field 'interests' must be a list of strings"}), 400
    if interests_list and not all(isinstance(item, str) for item in interests_list): return jsonify({"error": "All items in 'interests' list must be strings"}), 400
    
    referrer = None
    valid_referrer_id = None
    if referrer_id_from_request is not None:
        if not isinstance(referrer_id_from_request, int): return jsonify({"error": "Field 'referrer_id' must be an integer"}), 400
        referrer = User.query.get(referrer_id_from_request)
        if referrer is None: return jsonify({"error": f"Referrer user with ID {referrer_id_from_request} not found"}), 404
        else: valid_referrer_id = referrer.id
    
    new_user = User(name=name, email=email, phone_number=phone_number)
    new_user.set_password(password)
    new_user.set_interests(interests_list)
    if valid_referrer_id: new_user.referrer_id = valid_referrer_id
    new_user.set_referred_by_me_ids([])

    try:
        db.session.add(new_user)
        db.session.commit()
        app.logger.info(f"New user created with ID: {new_user.id}")
        if referrer:
            try:
                referred_ids = referrer.get_referred_by_me_ids()
                if new_user.id not in referred_ids:
                    referred_ids.append(new_user.id)
                    referrer.set_referred_by_me_ids(referred_ids)
                referrer.coins += 100 # Award coins to referrer
                app.logger.info(f"Awarding 100 coins to referrer {referrer.id}. New balance: {referrer.coins}")
                db.session.commit()
            except Exception as e_ref:
                db.session.rollback()
                app.logger.error(f"ERROR updating referrer {referrer.id} for new user {new_user.id}: {e_ref}", exc_info=True)
        return jsonify({"message": "User registered successfully!", "user": new_user.to_dict()}), 201
    except Exception as e_reg:
        db.session.rollback()
        app.logger.error(f"Registration Error: {e_reg}", exc_info=True)
        return jsonify({"error": "Internal Server Error during registration"}), 500

@app.route('/login', methods=['POST'])
def login():
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')
    if not email or not password: return jsonify({"error": "Missing email or password"}), 400
    user = User.query.filter_by(email=email).first()
    if user is None or not user.check_password(password): return jsonify({"error": "Invalid email or password"}), 401
    return jsonify({"message": "Login successful!", "user": user.to_dict()}), 200

@app.route('/users/<int:user_id>/spin_wheel', methods=['POST'])
def spin_wheel(user_id_param): # Renamed to avoid conflict with user_id from form
    user = User.query.get(user_id_param)
    if user is None: return jsonify({"error": f"User with ID {user_id_param} not found"}), 404
    now = datetime.utcnow()
    cooldown_period = timedelta(hours=24)
    can_spin = False
    remaining_time_str = ""
    remaining_seconds = 0

    if user.last_spin_time is None or (now - user.last_spin_time) >= cooldown_period:
        can_spin = True
    else:
        remaining_time = cooldown_period - (now - user.last_spin_time)
        remaining_seconds = int(remaining_time.total_seconds())
        hours, remainder = divmod(remaining_seconds, 3600)
        minutes, seconds_val = divmod(remainder, 60) # Renamed seconds to seconds_val
        remaining_time_str = f"{hours}h {minutes}m {seconds_val}s"

    if can_spin:
        try:
            # prize_coins = random.randint(10, 50) # Example
            # user.coins += prize_coins
            user.last_spin_time = now
            db.session.commit()
            app.logger.info(f"User {user_id_param} spin successful. Last spin time updated.")
            return jsonify({
                "status": 1,
                "message": "Spin successful! You can spin again in 24 hours.",
                "new_coins_balance": user.coins
            }), 200
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Error during spin for user {user_id_param}: {e}", exc_info=True)
            return jsonify({"error": "Internal server error processing spin"}), 500
    else:
        return jsonify({
            "status": 0,
            "message": f"Please wait. Time remaining: {remaining_time_str}",
            "remaining_seconds": remaining_seconds
        }), 200

@app.route('/users', methods=['GET'])
def get_all_users():
    try:
        all_users = User.query.all()
        return jsonify([user.to_dict(include_ads=False) for user in all_users]), 200
    except Exception as e:
        app.logger.error(f"Error fetching all users: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error fetching users"}), 500

@app.route('/users/<int:user_id>', methods=['GET'])
def get_user_by_id(user_id):
    user = User.query.get(user_id)
    if user is None: return jsonify({"error": f"User with ID {user_id} not found"}), 404
    return jsonify(user.to_dict(include_ads=False)), 200

@app.route('/profile/<int:user_id>', methods=['GET'])
def get_user_profile(user_id):
    user = User.query.get(user_id)
    if user is None: return jsonify({"error": f"User with ID {user_id} not found"}), 404
    try:
        return jsonify(user.to_dict(include_ads=True)), 200
    except Exception as e:
        app.logger.error(f"Error generating profile for user {user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error generating profile"}), 500

@app.route('/users/<int:user_id_param>/interests', methods=['PUT']) # Renamed user_id
def update_user_interests(user_id_param):
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    user = User.query.get(user_id_param)
    if user is None: return jsonify({"error": f"User with ID {user_id_param} not found"}), 404
    data = request.get_json()
    interests_list = data.get('interests')
    if interests_list is None: return jsonify({"error": "Missing 'interests' field"}), 400
    if not isinstance(interests_list, list) or not all(isinstance(i, str) for i in interests_list):
        return jsonify({"error": "'interests' must be a list of strings"}), 400
    try:
        user.set_interests(interests_list)
        db.session.commit()
        return jsonify({"message": "Interests updated", "user": user.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating interests for user {user_id_param}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/add_advertisement', methods=['POST'])
def add_advertisement():
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    user_id_from_data = data.get('user_id') # Renamed to avoid conflict
    if user_id_from_data is None: return jsonify({"error": "Missing 'user_id' field"}), 400
    
    user = User.query.get(user_id_from_data)
    if not user: return jsonify({"error": f"User {user_id_from_data} not found"}), 404

    new_ad = Advertisement(
        user_id=user_id_from_data, title=data.get('title'), link=data.get('link'),
        coin_per_click=data.get('coin_per_click'), description=data.get('description'),
        category=data.get('category'), subcategory=data.get('subcategory')
    )
    interests_list = data.get('interests')
    if interests_list is not None:
        if not isinstance(interests_list, list) or not all(isinstance(i, str) for i in interests_list):
             return jsonify({"error": "'interests' must be a list of strings or null."}), 400
        new_ad.set_interests(interests_list)
    
    if not all([new_ad.title, new_ad.link, new_ad.coin_per_click is not None]):
         return jsonify({"error": "Missing required fields: title, link, coin_per_click"}), 400
    if not isinstance(new_ad.coin_per_click, int) or new_ad.coin_per_click < 0:
         return jsonify({"error": "'coin_per_click' must be a non-negative integer"}), 400
    
    try:
        db.session.add(new_ad)
        db.session.commit()
        return jsonify({"message": "Advertisement submitted", "advertisement": new_ad.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating ad for user {user_id_from_data}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/admin/advertisements/<int:ad_id>/approve', methods=['PUT'])
def approve_advertisement(ad_id):
    # !! Add Admin Auth Check Here !!
    advertisement = Advertisement.query.get(ad_id)
    if advertisement is None: return jsonify({"error": "Ad not found"}), 404
    if advertisement.is_approved: return jsonify({"message": "Already approved"}), 200
    try:
        advertisement.is_approved = True
        advertisement.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"message": "Advertisement approved", "advertisement": advertisement.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error approving ad {ad_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/admin/advertisements/<int:ad_id>/reject', methods=['DELETE'])
def reject_and_delete_advertisement(ad_id):
    # !! Add Admin Auth Check Here !!
    app.logger.warning(f"Admin attempt: Reject/DELETE ad {ad_id}.")
    advertisement = Advertisement.query.get(ad_id)
    if advertisement is None:
        return jsonify({"error": f"Ad ID {ad_id} not found"}), 404
    try:
        db.session.delete(advertisement)
        db.session.commit()
        app.logger.info(f"Admin: Ad {ad_id} rejected and deleted.")
        return jsonify({"message": f"Advertisement {ad_id} rejected and deleted."}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error rejecting ad {ad_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500
# ... (الكود السابق) ...

@app.route('/admin/advertisements/force_delete/<int:ad_id>', methods=['DELETE'])
def force_delete_advertisement(ad_id):
    """
    نقطة نهاية لحذف إعلان معين بالقوة بدون التحقق من الملكية.
    !!! تحذير: هذه نقطة نهاية خطيرة ويجب تأمينها أو استخدامها بحذر شديد !!!
    """
    app.logger.warning(f"Executing FORCE DELETE for advertisement ID: {ad_id}. This is a high-privilege operation.")

    advertisement = Advertisement.query.get(ad_id)

    if advertisement is None:
        app.logger.warning(f"FORCE DELETE failed: Advertisement with ID {ad_id} not found.")
        return jsonify({"error": f"Advertisement with ID {ad_id} not found"}), 404

    try:
        db.session.delete(advertisement)
        db.session.commit()
        app.logger.info(f"Advertisement {ad_id} was FORCE DELETED successfully.")
        return jsonify({"message": f"Advertisement {ad_id} force deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error during FORCE DELETE of advertisement {ad_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error during force deletion"}), 500

# ... (باقي الكود) ...
@app.route('/advertisements', methods=['GET'])
def get_advertisements_filtered():
    try:
        query = Advertisement.query
        if request.args.get('user_id'): query = query.filter(Advertisement.user_id == int(request.args.get('user_id')))
        if request.args.get('category'): query = query.filter(Advertisement.category == request.args.get('category'))
        # ... (Add other filters as in original code) ...
        if request.args.get('is_approved'):
            is_approved_filter = request.args.get('is_approved').lower()
            if is_approved_filter == 'true': query = query.filter(Advertisement.is_approved == True)
            elif is_approved_filter == 'false': query = query.filter(Advertisement.is_approved == False)
        
        # Simplified for brevity, add all original filters back
        filtered_ads = query.order_by(Advertisement.created_at.desc()).all()
        return jsonify([ad.to_dict() for ad in filtered_ads]), 200
    except ValueError as ve:
        return jsonify({"error": f"Invalid parameter value: {ve}"}), 400
    except Exception as e:
        app.logger.error(f"Error fetching/filtering ads: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/advertisements/approved', methods=['GET'])
def get_approved_advertisements():
    try:
        approved_ads = Advertisement.query.filter_by(is_approved=True, is_active=True)\
                                          .order_by(Advertisement.created_at.desc()).all()
        return jsonify([ad.to_dict() for ad in approved_ads]), 200
    except Exception as e:
        app.logger.error(f"Error fetching approved ads: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/users/<int:user_id_param>/advertisements', methods=['GET']) # Renamed user_id
def get_user_advertisements(user_id_param):
    user = User.query.get(user_id_param)
    if user is None: return jsonify({"error": f"User ID {user_id_param} not found"}), 404
    try:
        # user_ads = user.advertisements # Using relationship
        user_ads = Advertisement.query.filter_by(user_id=user_id_param)\
                                     .order_by(Advertisement.created_at.desc()).all()
        return jsonify([ad.to_dict() for ad in user_ads]), 200
    except Exception as e:
        app.logger.error(f"Error fetching ads for user {user_id_param}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

# --- Image Analysis Endpoints (MODIFIED) ---

@app.route('/analyze_like_status', methods=['POST'])
def analyze_like_status():
    if not gemini_model:
        app.logger.warning("Gemini model N/A for like analysis.")
        return jsonify({"error": "Image analysis service unavailable."}), 503

    user, error_response = get_validated_user_from_form(request.form)
    if error_response: return error_response
    user_id = user.id # Get user_id from the validated user object

    if 'image' not in request.files: return jsonify({"error": "Missing 'image' file part."}), 400
    file = request.files['image']
    if file.filename == '': return jsonify({"error": "No file selected."}), 400

    try:
        img_bytes = file.read()
        if not img_bytes: return jsonify({"error": "Empty image file."}), 400
        img_hash = hashlib.sha256(img_bytes).hexdigest()
    except Exception as e:
        app.logger.error(f"User {user_id}: Img hash error: {e}", exc_info=True)
        return jsonify({"error": "Could not process image file."}), 400

    image_user_pair = (user_id, img_hash)
    if image_user_pair in processed_image_hashes:
        app.logger.warning(f"User {user_id}: Duplicate img for like: {img_hash}")
        return jsonify({"status": -1, "message": "Image already processed by you."}), 200

    try:
        img = Image.open(io.BytesIO(img_bytes))
        img.verify()
        img = Image.open(io.BytesIO(img_bytes)) # Re-open
    except Exception as e:
        app.logger.error(f"User {user_id}: Invalid img (hash {img_hash}): {e}", exc_info=True)
        return jsonify({"error": "Invalid or corrupted image."}), 400

    try:
        app.logger.info(f"User {user_id}: Sending img {img_hash} to Gemini (like)...")
        response = gemini_model.generate_content([LIKE_DETECTION_PROMPT, img])
        if response.parts:
            raw_result = response.text.strip()
            app.logger.info(f"User {user_id}: Gemini like raw_result for {img_hash}: '{raw_result}'")
            if raw_result in ["1", "0"]:
                processed_image_hashes.add(image_user_pair)
                app.logger.info(f"User {user_id}: Pair {image_user_pair} added. Set size: {len(processed_image_hashes)}")
                # Potentially award coins here if raw_result == "1" and task is valid
                # Example: if raw_result == "1": user.coins += 1; db.session.commit()
                return jsonify({"status": int(raw_result), "message": "Analysis complete."}), 200
            else:
                app.logger.error(f"User {user_id}: Unexpected Gemini (like) for {img_hash}: '{raw_result}'")
                return jsonify({"error": f"Unexpected analysis result: '{raw_result}'"}), 500
        else:
            feedback = response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'
            app.logger.error(f"User {user_id}: Gemini no content (like) for {img_hash}. Feedback: {feedback}")
            return jsonify({"error": "Analysis failed or content blocked."}), 500
    except Exception as e:
        app.logger.error(f"User {user_id}: Gemini API error (like) for {img_hash}: {e}", exc_info=True)
        return jsonify({"error": f"Image analysis error: {str(e)}"}), 500

@app.route('/analyze_comment_status', methods=['POST'])
def analyze_comment_status():
    if not gemini_model:
        app.logger.warning("Gemini model N/A for comment analysis.")
        return jsonify({"error": "Image analysis service unavailable."}), 503

    user, error_response = get_validated_user_from_form(request.form)
    if error_response: return error_response
    user_id = user.id

    if 'username' not in request.form: return jsonify({"error": "Missing 'username' form field."}), 400
    username = request.form['username']
    if not username: return jsonify({"error": "'username' cannot be empty."}), 400

    if 'image' not in request.files: return jsonify({"error": "Missing 'image' file part."}), 400
    file = request.files['image']
    if file.filename == '': return jsonify({"error": "No file selected."}), 400

    try:
        img_bytes = file.read()
        if not img_bytes: return jsonify({"error": "Empty image file."}), 400
        img_hash = hashlib.sha256(img_bytes).hexdigest()
    except Exception as e:
        app.logger.error(f"User {user_id}: Img hash error (comment): {e}", exc_info=True)
        return jsonify({"error": "Could not process image file."}), 400

    image_user_pair = (user_id, img_hash)
    if image_user_pair in processed_image_hashes:
        app.logger.warning(f"User {user_id}: Duplicate img for comment: {img_hash}")
        return jsonify({"status": -1, "message": "Image already processed by you."}), 200
    
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img.verify()
        img = Image.open(io.BytesIO(img_bytes))
    except Exception as e:
        app.logger.error(f"User {user_id}: Invalid img (comment, hash {img_hash}): {e}", exc_info=True)
        return jsonify({"error": "Invalid or corrupted image."}), 400

    try:
        comment_prompt = COMMENT_DETECTION_PROMPT.format(username=username)
        app.logger.info(f"User {user_id}: Sending img {img_hash} to Gemini (comment for '{username}')...")
        response = gemini_model.generate_content([comment_prompt, img])
        if response.parts:
            raw_result = response.text.strip()
            app.logger.info(f"User {user_id}: Gemini comment raw_result for {img_hash} ('{username}'): '{raw_result}'")
            if raw_result in ["1", "0"]:
                processed_image_hashes.add(image_user_pair)
                app.logger.info(f"User {user_id}: Pair {image_user_pair} added. Set size: {len(processed_image_hashes)}")
                # Potentially award coins
                return jsonify({"status": int(raw_result), "message": f"Comment analysis for '{username}' complete."}), 200
            else:
                app.logger.error(f"User {user_id}: Unexpected Gemini (comment) for {img_hash}: '{raw_result}'")
                return jsonify({"error": f"Unexpected analysis result: '{raw_result}'"}), 500
        else:
            feedback = response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'
            app.logger.error(f"User {user_id}: Gemini no content (comment) for {img_hash}. Feedback: {feedback}")
            return jsonify({"error": "Analysis failed or content blocked."}), 500
    except Exception as e:
        app.logger.error(f"User {user_id}: Gemini API error (comment) for {img_hash}: {e}", exc_info=True)
        return jsonify({"error": f"Image analysis error: {str(e)}"}), 500

@app.route('/analyze_share_status', methods=['POST'])
def analyze_share_status():
    if not gemini_model:
        app.logger.warning("Gemini model N/A for share analysis.")
        return jsonify({"error": "Image analysis service unavailable."}), 503

    user, error_response = get_validated_user_from_form(request.form)
    if error_response: return error_response
    user_id = user.id

    if 'image' not in request.files: return jsonify({"error": "Missing 'image' file part."}), 400
    file = request.files['image']
    if file.filename == '': return jsonify({"error": "No file selected."}), 400

    try:
        img_bytes = file.read()
        if not img_bytes: return jsonify({"error": "Empty image file."}), 400
        img_hash = hashlib.sha256(img_bytes).hexdigest()
    except Exception as e:
        app.logger.error(f"User {user_id}: Img hash error (share): {e}", exc_info=True)
        return jsonify({"error": "Could not process image file."}), 400

    image_user_pair = (user_id, img_hash)
    if image_user_pair in processed_image_hashes:
        app.logger.warning(f"User {user_id}: Duplicate img for share: {img_hash}")
        return jsonify({"status": -1, "message": "Image already processed by you."}), 200

    try:
        img = Image.open(io.BytesIO(img_bytes))
        img.verify()
        img = Image.open(io.BytesIO(img_bytes))
    except Exception as e:
        app.logger.error(f"User {user_id}: Invalid img (share, hash {img_hash}): {e}", exc_info=True)
        return jsonify({"error": "Invalid or corrupted image."}), 400

    try:
        app.logger.info(f"User {user_id}: Sending img {img_hash} to Gemini (share)...")
        response = gemini_model.generate_content([SHARE_DETECTION_PROMPT, img])
        if response.parts:
            raw_result = response.text.strip()
            app.logger.info(f"User {user_id}: Gemini share raw_result for {img_hash}: '{raw_result}'")
            if raw_result in ["1", "0"]:
                processed_image_hashes.add(image_user_pair)
                app.logger.info(f"User {user_id}: Pair {image_user_pair} added. Set size: {len(processed_image_hashes)}")
                return jsonify({"status": int(raw_result), "message": "Share analysis complete."}), 200
            else:
                app.logger.error(f"User {user_id}: Unexpected Gemini (share) for {img_hash}: '{raw_result}'")
                return jsonify({"error": f"Unexpected analysis result: '{raw_result}'"}), 500
        else:
            feedback = response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'
            app.logger.error(f"User {user_id}: Gemini no content (share) for {img_hash}. Feedback: {feedback}")
            return jsonify({"error": "Analysis failed or content blocked."}), 500
    except Exception as e:
        app.logger.error(f"User {user_id}: Gemini API error (share) for {img_hash}: {e}", exc_info=True)
        return jsonify({"error": f"Image analysis error: {str(e)}"}), 500

@app.route('/analyze_subscribe_status', methods=['POST'])
def analyze_subscribe_status():
    if not gemini_model:
        app.logger.warning("Gemini model N/A for subscribe analysis.")
        return jsonify({"error": "Image analysis service unavailable."}), 503

    user, error_response = get_validated_user_from_form(request.form)
    if error_response: return error_response
    user_id = user.id

    if 'image' not in request.files: return jsonify({"error": "Missing 'image' file part."}), 400
    file = request.files['image']
    if file.filename == '': return jsonify({"error": "No file selected."}), 400

    try:
        img_bytes = file.read()
        if not img_bytes: return jsonify({"error": "Empty image file."}), 400
        img_hash = hashlib.sha256(img_bytes).hexdigest()
    except Exception as e:
        app.logger.error(f"User {user_id}: Img hash error (subscribe): {e}", exc_info=True)
        return jsonify({"error": "Could not process image file."}), 400

    image_user_pair = (user_id, img_hash)
    if image_user_pair in processed_image_hashes:
        app.logger.warning(f"User {user_id}: Duplicate img for subscribe: {img_hash}")
        return jsonify({"status": -1, "message": "Image already processed by you."}), 200

    try:
        img = Image.open(io.BytesIO(img_bytes))
        img.verify()
        img = Image.open(io.BytesIO(img_bytes))
    except Exception as e:
        app.logger.error(f"User {user_id}: Invalid img (subscribe, hash {img_hash}): {e}", exc_info=True)
        return jsonify({"error": "Invalid or corrupted image."}), 400

    try:
        app.logger.info(f"User {user_id}: Sending img {img_hash} to Gemini (subscribe)...")
        response = gemini_model.generate_content([SUBSCRIBE_DETECTION_PROMPT, img])
        if response.parts:
            raw_result = response.text.strip()
            app.logger.info(f"User {user_id}: Gemini subscribe raw_result for {img_hash}: '{raw_result}'")
            if raw_result in ["1", "0"]:
                processed_image_hashes.add(image_user_pair)
                app.logger.info(f"User {user_id}: Pair {image_user_pair} added. Set size: {len(processed_image_hashes)}")
                return jsonify({"status": int(raw_result), "message": "Subscription analysis complete."}), 200
            else:
                app.logger.error(f"User {user_id}: Unexpected Gemini (subscribe) for {img_hash}: '{raw_result}'")
                return jsonify({"error": f"Unexpected analysis result: '{raw_result}'"}), 500
        else:
            feedback = response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'
            app.logger.error(f"User {user_id}: Gemini no content (subscribe) for {img_hash}. Feedback: {feedback}")
            return jsonify({"error": "Analysis failed or content blocked."}), 500
    except Exception as e:
        app.logger.error(f"User {user_id}: Gemini API error (subscribe) for {img_hash}: {e}", exc_info=True)
        return jsonify({"error": f"Image analysis error: {str(e)}"}), 500
@app.route('/advertisements/<int:ad_id>/click', methods=['POST'])
def click_advertisement(ad_id):
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    data = request.get_json()
    clicking_user_id = data.get('user_id') # ID المستخدم الذي قام بالنقر

    if clicking_user_id is None:
        return jsonify({"error": "Missing 'user_id' in request body (user who clicked)"}), 400

    try:
        clicking_user_id = int(clicking_user_id)
    except ValueError:
        return jsonify({"error": "'user_id' must be an integer"}), 400

    advertisement = Advertisement.query.get(ad_id)
    clicking_user = User.query.get(clicking_user_id)

    if not advertisement:
        return jsonify({"error": f"Advertisement with ID {ad_id} not found"}), 404
    
    if not clicking_user:
        return jsonify({"error": f"User (clicker) with ID {clicking_user_id} not found"}), 404

    if not advertisement.is_approved or not advertisement.is_active:
        return jsonify({"error": "This advertisement is not active or approved for clicks"}), 403

    clicked_ids = advertisement.get_clicked_by_user_ids()
    if clicking_user_id in clicked_ids:
        app.logger.info(f"User {clicking_user_id} already clicked Ad {ad_id}. No new coins awarded to advertiser.")
        return jsonify({
            "message": "You have already interacted with this advertisement.",
            "advertisement_id": ad_id,
            "number_of_clicks": advertisement.number_of_clicks # إرجاع العدد الحالي
        }), 200 # 200 OK لأن العملية "مفهومة" ولكن لم يتم اتخاذ إجراء جديد


    # --- الحصول على صاحب الإعلان لمنحه العملات ---
    advertiser = User.query.get(advertisement.user_id)
    if not advertiser:
        # هذا يجب ألا يحدث إذا كانت البيانات متناسقة
        app.logger.error(f"CRITICAL: Advertiser (User ID {advertisement.user_id}) for Ad {ad_id} not found!")
        return jsonify({"error": "Internal server error: Advertiser not found"}), 500

    try:
        # 1. تحديث قائمة الناقرين على الإعلان
        clicked_ids.append(clicking_user_id)
        advertisement.set_clicked_by_user_ids(clicked_ids)
        
        # 2. زيادة عدد النقرات الإجمالي
        advertisement.number_of_clicks += 1
        
        # 3. منح العملات لصاحب الإعلان
        coins_to_award = advertisement.coin_per_click
        advertiser.coins += coins_to_award
        
        advertisement.updated_at = datetime.utcnow() # تحديث وقت تعديل الإعلان

        db.session.commit()
        app.logger.info(f"User {clicking_user_id} clicked Ad {ad_id}. Advertiser {advertiser.id} awarded {coins_to_award} coins. New balance: {advertiser.coins}")
        
        return jsonify({
            "message": "Advertisement clicked successfully!",
            "advertisement_id": ad_id,
            "new_total_clicks_on_ad": advertisement.number_of_clicks,
            "coins_awarded_to_advertiser": coins_to_award,
            "advertiser_new_coin_balance": advertiser.coins,
            "clicked_by_user_ids": advertisement.get_clicked_by_user_ids() # عرض القائمة المحدثة
        }), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error processing click on Ad {ad_id} by User {clicking_user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error during click processing"}), 500
@app.route('/users/<int:user_id_param>', methods=['PATCH']) # Renamed user_id
def update_user_data(user_id_param):
    user = User.query.get(user_id_param)
    if user is None: return jsonify({"error": f"User ID {user_id_param} not found"}), 404
    if not request.is_json: return jsonify({"error": "Request must be JSON"}), 400
    data = request.get_json()
    if not data: return jsonify({"error": "Request body cannot be empty"}), 400
    
    updated_fields = []
    if 'name' in data:
        user.name = data['name']
        updated_fields.append('name')
    if 'phone_number' in data:
        user.phone_number = data['phone_number']
        updated_fields.append('phone_number')
    if 'interests' in data:
        user.set_interests(data['interests'])
        updated_fields.append('interests')
    if 'add_coins' in data:
        try:
            user.coins += int(data['add_coins'])
            updated_fields.append('coins_added')
        except (ValueError, TypeError): return jsonify({"error": "'add_coins' must be int"}),400
    if 'subtract_coins' in data:
        try:
            amount_to_subtract = int(data['subtract_coins'])
            user.coins = max(0, user.coins - amount_to_subtract)
            updated_fields.append('coins_subtracted')
        except (ValueError, TypeError): return jsonify({"error": "'subtract_coins' must be int"}),400

    if not updated_fields: return jsonify({"message": "No valid fields to update."}), 200

    try:
        db.session.commit()
        app.logger.info(f"User {user_id_param}: Updated fields: {', '.join(updated_fields)}")
        return jsonify({"message": "User data updated", "user": user.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating user {user_id_param}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

# --- التشغيل المحلي ---
if __name__ == '__main__':
    print("Starting Flask development server (for local testing)...")
    app.run(debug=True, host='0.0.0.0', port=5000)
