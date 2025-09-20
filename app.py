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
persistent_data_dir = '/tmp' # أو المسار المناسب لبيئتك (للإنتاج، استخدم مسار دائم)
db_path = os.path.join(persistent_data_dir, 'databases5.db') # تم تغيير اسم قاعدة البيانات لضمان إنشاء جديد إذا لزم الأمر
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
        gemini_model = genai.GenerativeModel('gemini-1.5-flash') # تم التغيير إلى فلاش الأحدث
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

# --- قيم العملات للمهام ---
COIN_VALUES = {
    "like": 5,
    "comment": 7,
    "share": 10,
    "subscribe": 12
}
POSSIBLE_ACTION_TYPES = set(COIN_VALUES.keys())

# --- (أعلى الملف مع بقية تعريفات الموديلات) ---

# ... (موديل User و Advertisement و UserAdAction كما هي) ...

class CoinPackage(db.Model):
    __tablename__ = 'coin_package'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True) # اسم الباقة، مثال: "باقة 1000 عملة"
    amount = db.Column(db.Integer, nullable=False) # عدد العملات في الباقة
    price_usd = db.Column(db.Float, nullable=True) # السعر بالدولار الأمريكي (أو عملتك المفضلة) - اجعله True إذا كان السعر اختياريًا
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True) # هل الباقة متاحة حاليًا
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "amount": self.amount,
            "price_usd": self.price_usd,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<CoinPackage {self.id} - {self.name} ({self.amount} coins)>'

# --- (بعد تعريف الموديل، وقبل db.create_all() إذا كنت ستشغلها يدويًا) ---
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
    # علاقة جديدة مع UserAdAction
    # ad_actions = db.relationship('UserAdAction', backref='user', lazy='dynamic') # تم تعريفها في UserAdAction

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

class Advertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True) # صاحب الإعلان
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    link = db.Column(db.Text, nullable=False)
    interests = db.Column(db.Text, nullable=True)
    number_of_clicks = db.Column(db.Integer, nullable=False, default=0) # نقرات على الرابط
    coin_per_click = db.Column(db.Integer, nullable=False) # عملات لصاحب الإعلان عن كل نقرة على الرابط
    category = db.Column(db.String(80), nullable=True, index=True)
    subcategory = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    is_approved = db.Column(db.Boolean, nullable=False, default=False, index=True)
    clicked_by_user_ids = db.Column(db.Text, nullable=True) # مستخدمون نقروا على الرابط
    # علاقة جديدة مع UserAdAction
    # user_actions = db.relationship('UserAdAction', backref='advertisement', lazy='dynamic') # تم تعريفها في UserAdAction

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

    def set_clicked_by_user_ids(self, id_list):
        if id_list and isinstance(id_list, list):
            if all(isinstance(item, int) for item in id_list):
                self.clicked_by_user_ids = json.dumps(id_list)
            else:
                app.logger.warning(f"Ad {self.id}: clicked_by_user_ids list contains non-integer elements. Setting to empty list.")
                self.clicked_by_user_ids = json.dumps([])
        else:
            self.clicked_by_user_ids = json.dumps([])

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
            "user_id": self.user_id,
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
            "clicked_by_user_ids": self.get_clicked_by_user_ids()
        }

    def __repr__(self):
        return f'<Advertisement {self.id} - {self.title} by User {self.user_id}>'


# --- موديل UserAdAction الجديد ---
class UserAdAction(db.Model):
    __tablename__ = 'user_ad_action'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    advertisement_id = db.Column(db.Integer, db.ForeignKey('advertisement.id'), nullable=False, index=True)
    action_type = db.Column(db.String(50), nullable=False, index=True) # e.g., 'like', 'comment', 'share', 'subscribe'
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # لضمان عدم تكرار نفس الإجراء من نفس المستخدم على نفس الإعلان
    __table_args__ = (db.UniqueConstraint('user_id', 'advertisement_id', 'action_type', name='uq_user_ad_action'),)

    user = db.relationship('User', backref=db.backref('ad_actions', lazy='dynamic'))
    advertisement = db.relationship('Advertisement', backref=db.backref('user_actions', lazy='dynamic'))

    def __repr__(self):
        return f'<UserAdAction User {self.user_id} {self.action_type} Ad {self.advertisement_id}>'


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

# --- START: Helper function to get user_id and validate user ---
def get_validated_user_from_form(form_data):
    if 'user_id' not in form_data:
        app.logger.warning("Missing 'user_id' in form data.")
        return None, (jsonify({"error": "Missing 'user_id' form field in the request."}), 400)
    user_id_str = form_data.get('user_id')
    try:
        user_id_val = int(user_id_str)
    except (ValueError, TypeError):
        app.logger.warning(f"Invalid user_id format: {user_id_str}")
        return None, (jsonify({"error": "'user_id' must be a valid integer."}), 400)

    user = User.query.get(user_id_val)
    if not user:
        app.logger.warning(f"User with ID {user_id_val} not found.")
        return None, (jsonify({"error": f"User with ID {user_id_val} not found."}), 404)
    return user, None
# --- END: Helper function ---

# --- نقاط النهاية (API Endpoints) ---

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

@app.route('/users/<int:user_id_param>/spin_wheel', methods=['POST'])
def spin_wheel(user_id_param): 
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
        minutes, seconds_val = divmod(remainder, 60)
        remaining_time_str = f"{hours}h {minutes}m {seconds_val}s"

    if can_spin:
        try:
            # prize_coins = random.randint(10, 50) # Example: Implement actual prize logic
            # user.coins += prize_coins
            user.last_spin_time = now
            db.session.commit()
            app.logger.info(f"User {user_id_param} spin successful. Last spin time updated.")
            return jsonify({
                "status": 1,
                "message": "Spin successful! You can spin again in 24 hours.",
                "new_coins_balance": user.coins # Ensure this reflects any prize coins awarded
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

@app.route('/users/<int:user_id_param>/interests', methods=['PUT'])
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
    user_id_from_data = data.get('user_id')
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
        # قبل الحذف، قد ترغب في حذف الإجراءات المرتبطة به من UserAdAction
        UserAdAction.query.filter_by(advertisement_id=ad_id).delete()
        db.session.delete(advertisement)
        db.session.commit()
        app.logger.info(f"Admin: Ad {ad_id} and its actions rejected and deleted.")
        return jsonify({"message": f"Advertisement {ad_id} rejected and deleted."}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error rejecting ad {ad_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/admin/advertisements/force_delete/<int:ad_id>', methods=['DELETE'])
def force_delete_advertisement(ad_id):
    # !! Add Admin Auth Check Here !!
    app.logger.warning(f"Executing FORCE DELETE for advertisement ID: {ad_id}. This is a high-privilege operation.")
    advertisement = Advertisement.query.get(ad_id)
    if advertisement is None:
        app.logger.warning(f"FORCE DELETE failed: Advertisement with ID {ad_id} not found.")
        return jsonify({"error": f"Advertisement with ID {ad_id} not found"}), 404
    try:
        UserAdAction.query.filter_by(advertisement_id=ad_id).delete() # حذف الإجراءات المرتبطة
        db.session.delete(advertisement)
        db.session.commit()
        app.logger.info(f"Advertisement {ad_id} and its actions were FORCE DELETED successfully.")
        return jsonify({"message": f"Advertisement {ad_id} force deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error during FORCE DELETE of advertisement {ad_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error during force deletion"}), 500

@app.route('/advertisements', methods=['GET'])
def get_advertisements_filtered(): # نقطة نهاية عامة لفلترة الإعلانات (يمكن استخدامها من قبل المشرفين مثلاً)
    try:
        query = Advertisement.query
        if request.args.get('user_id'): query = query.filter(Advertisement.user_id == int(request.args.get('user_id')))
        if request.args.get('category'): query = query.filter(Advertisement.category == request.args.get('category'))
        if request.args.get('is_approved'):
            is_approved_filter = request.args.get('is_approved').lower()
            if is_approved_filter == 'true': query = query.filter(Advertisement.is_approved == True)
            elif is_approved_filter == 'false': query = query.filter(Advertisement.is_approved == False)
        
        filtered_ads = query.order_by(Advertisement.created_at.desc()).all()
        return jsonify([ad.to_dict() for ad in filtered_ads]), 200
    except ValueError as ve:
        return jsonify({"error": f"Invalid parameter value: {ve}"}), 400
    except Exception as e:
        app.logger.error(f"Error fetching/filtering ads: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/users/<int:user_id_param>/advertisements', methods=['GET'])
def get_user_advertisements(user_id_param): # إعلانات أنشأها المستخدم
    user = User.query.get(user_id_param)
    if user is None: return jsonify({"error": f"User ID {user_id_param} not found"}), 404
    try:
        user_ads = Advertisement.query.filter_by(user_id=user_id_param)\
                                     .order_by(Advertisement.created_at.desc()).all()
        return jsonify([ad.to_dict() for ad in user_ads]), 200
    except Exception as e:
        app.logger.error(f"Error fetching ads for user {user_id_param}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500


# --- نقطة نهاية جديدة لجلب الإعلانات المتاحة للمستخدم مع المهام ---
@app.route('/advertisements/available_for_user/<int:requesting_user_id>', methods=['GET'])
def get_available_ads_for_user(requesting_user_id):
    user = User.query.get(requesting_user_id)
    if not user:
        return jsonify({"error": f"User with ID {requesting_user_id} not found."}), 404

    try:
        actions_done_by_user_raw = db.session.query(
                                        UserAdAction.advertisement_id, 
                                        UserAdAction.action_type
                                     )\
                                     .filter(UserAdAction.user_id == requesting_user_id)\
                                     .all()
        
        interacted_ads_actions = {}
        for ad_id_val, action_type_val in actions_done_by_user_raw:
            if ad_id_val not in interacted_ads_actions:
                interacted_ads_actions[ad_id_val] = set()
            interacted_ads_actions[ad_id_val].add(action_type_val)

        app.logger.debug(f"User {requesting_user_id} has interacted with ads and actions: {interacted_ads_actions}")

        query = Advertisement.query.filter(
            Advertisement.is_approved == True,
            Advertisement.is_active == True
        )
        
        # فلترة بالاهتمامات (مثال بسيط)
        user_interests = user.get_interests()
        if user_interests:
            # هذا يتطلب أن يكون Advertisement.interests هو JSON array of strings
            # وقد يكون أبطأ مع SQLite لقواعد البيانات الكبيرة
            # for interest in user_interests:
            # query = query.filter(Advertisement.interests.contains(interest)) # Requires specific DB setup for JSON search
            # حل أبسط: الفلترة بعد الجلب إذا كانت القائمة ليست ضخمة جدًا
            pass


        all_potential_ads = query.order_by(Advertisement.created_at.desc()).all()
        
        available_ads_with_tasks = []

        for ad in all_potential_ads:
            # فلترة بالاهتمامات (بعد الجلب) - إذا لم يتم تطبيقها في الاستعلام
            # ad_interests = ad.get_interests()
            # if user_interests and ad_interests and not any(i in ad_interests for i in user_interests):
            # continue # تخطي الإعلان إذا لم يكن هناك اهتمامات مشتركة

            remaining_tasks_for_ad = list(POSSIBLE_ACTION_TYPES - interacted_ads_actions.get(ad.id, set()))
            
            if remaining_tasks_for_ad:
                ad_data = ad.to_dict()
                ad_data['available_tasks'] = sorted(list(remaining_tasks_for_ad)) # ضمان ترتيب ثابت
                available_ads_with_tasks.append(ad_data)
        
        app.logger.info(f"Found {len(available_ads_with_tasks)} ads with available tasks for user {requesting_user_id} after filtering.")
        return jsonify(available_ads_with_tasks), 200

    except Exception as e:
        app.logger.error(f"Error fetching available ads for user {requesting_user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500


# --- Image Analysis Endpoints (MODIFIED) ---

def _analyze_social_action(action_type_constant, specific_prompt, request_data, request_files):
    """Helper function to reduce redundancy in analysis endpoints."""
    if not gemini_model:
        app.logger.warning(f"Gemini model N/A for {action_type_constant} analysis.")
        return jsonify({"error": "Image analysis service unavailable."}), 503

    user, error_response = get_validated_user_from_form(request_data)
    if error_response: return error_response
    user_id_val = user.id

    if 'advertisement_id' not in request_data:
        app.logger.warning(f"User {user_id_val}: Missing 'advertisement_id' in form for {action_type_constant} analysis.")
        return jsonify({"error": "Missing 'advertisement_id' form field."}), 400
    try:
        advertisement_id_val = int(request_data.get('advertisement_id'))
    except (ValueError, TypeError):
        app.logger.warning(f"User {user_id_val}: Invalid advertisement_id format: {request_data.get('advertisement_id')}")
        return jsonify({"error": "'advertisement_id' must be a valid integer."}), 400

    advertisement = Advertisement.query.get(advertisement_id_val)
    if not advertisement:
        app.logger.warning(f"User {user_id_val}: Advertisement with ID {advertisement_id_val} not found for {action_type_constant} analysis.")
        return jsonify({"error": f"Advertisement with ID {advertisement_id_val} not found."}), 404

    if 'image' not in request_files: return jsonify({"error": "Missing 'image' file part."}), 400
    file = request_files['image']
    if file.filename == '': return jsonify({"error": "No file selected."}), 400

    try:
        img_bytes = file.read()
        if not img_bytes: return jsonify({"error": "Empty image file."}), 400
        img_hash = hashlib.sha256(img_bytes).hexdigest()
    except Exception as e:
        app.logger.error(f"User {user_id_val}: Img hash error ({action_type_constant}): {e}", exc_info=True)
        return jsonify({"error": "Could not process image file."}), 400

    image_user_pair = (user_id_val, img_hash)
    if image_user_pair in processed_image_hashes:
        app.logger.warning(f"User {user_id_val}: Duplicate img for {action_type_constant} (hash {img_hash}) Ad {advertisement_id_val}")
        return jsonify({"status": -1, "message": "Image already processed by you for a task."}), 200

    existing_action = UserAdAction.query.filter_by(
        user_id=user_id_val,
        advertisement_id=advertisement_id_val,
        action_type=action_type_constant
    ).first()
    if existing_action:
        app.logger.warning(f"User {user_id_val} already performed '{action_type_constant}' on Ad {advertisement_id_val}.")
        return jsonify({"status": -2, "message": f"You have already performed this '{action_type_constant}' action on this advertisement."}), 200

    try:
        img = Image.open(io.BytesIO(img_bytes))
        img.verify()
        img = Image.open(io.BytesIO(img_bytes))
    except Exception as e:
        app.logger.error(f"User {user_id_val}: Invalid img ({action_type_constant}, hash {img_hash}) Ad {advertisement_id_val}: {e}", exc_info=True)
        return jsonify({"error": "Invalid or corrupted image."}), 400

    try:
        app.logger.info(f"User {user_id_val}: Sending img {img_hash} to Gemini ({action_type_constant}) for Ad {advertisement_id_val}...")
        final_prompt = specific_prompt
        if action_type_constant == "comment": # خاص بالتعليق، يحتاج لاسم المستخدم
            if 'username' not in request_data:
                 app.logger.warning(f"User {user_id_val}: Missing 'username' for comment analysis, Ad {advertisement_id_val}.")
                 return jsonify({"error": "Missing 'username' form field for comment analysis."}), 400
            username = request_data['username']
            if not username:
                app.logger.warning(f"User {user_id_val}: Empty 'username' for comment analysis, Ad {advertisement_id_val}.")
                return jsonify({"error": "'username' cannot be empty for comment analysis."}), 400
            final_prompt = specific_prompt.format(username=username)
            app.logger.info(f"User {user_id_val}: Using comment prompt for user '{username}'")


        response = gemini_model.generate_content([final_prompt, img])
        if response.parts:
            raw_result = response.text.strip()
            app.logger.info(f"User {user_id_val}: Gemini {action_type_constant} raw_result for {img_hash} Ad {advertisement_id_val}: '{raw_result}'")
            if raw_result == "1":
                processed_image_hashes.add(image_user_pair)
                app.logger.info(f"User {user_id_val}: Pair {image_user_pair} added for {action_type_constant}. Set size: {len(processed_image_hashes)}")
                
                new_action_obj = UserAdAction(
                    user_id=user_id_val,
                    advertisement_id=advertisement_id_val,
                    action_type=action_type_constant
                )
                db.session.add(new_action_obj)
                
                coins_to_award = COIN_VALUES.get(action_type_constant, 0)
                user.coins += coins_to_award
                app.logger.info(f"User {user_id_val} awarded {coins_to_award} coins for {action_type_constant} on Ad {advertisement_id_val}. Action prepared. New balance: {user.coins}")

                try:
                    db.session.commit()
                    app.logger.info(f"User {user_id_val}: Action '{action_type_constant}' for Ad {advertisement_id_val} and coin update committed.")
                except Exception as commit_ex:
                    db.session.rollback()
                    app.logger.error(f"User {user_id_val}: CRITICAL: Commit failed for {action_type_constant} Ad {advertisement_id_val} after Gemini success: {commit_ex}", exc_info=True)
                    processed_image_hashes.discard(image_user_pair) # محاولة التراجع عن إضافة الهاش إذا فشل الـ commit
                    return jsonify({"error": "Failed to record action due to a server error. Please try again."}), 500

                return jsonify({"status": int(raw_result), "message": f"{action_type_constant.capitalize()} analysis complete. Action logged and {coins_to_award} coins awarded."}), 200
            elif raw_result == "0":
                 return jsonify({"status": int(raw_result), "message": f"{action_type_constant.capitalize()} analysis complete. Action not detected."}), 200
            else:
                app.logger.error(f"User {user_id_val}: Unexpected Gemini ({action_type_constant}) for {img_hash} Ad {advertisement_id_val}: '{raw_result}'")
                return jsonify({"error": f"Unexpected analysis result: '{raw_result}'"}), 500
        else:
            feedback = response.prompt_feedback if hasattr(response, 'prompt_feedback') else 'N/A'
            app.logger.error(f"User {user_id_val}: Gemini no content ({action_type_constant}) for {img_hash} Ad {advertisement_id_val}. Feedback: {feedback}")
            # إذا كان هناك حظر محتوى، قد لا نرغب في إضافة الهاش
            # processed_image_hashes.add(image_user_pair) # فكر في هذا السطر
            return jsonify({"error": "Analysis failed or content blocked by safety filters."}), 500
    except Exception as e:
        app.logger.error(f"User {user_id_val}: Gemini API error ({action_type_constant}) for {img_hash} Ad {advertisement_id_val}: {e}", exc_info=True)
        return jsonify({"error": f"Image analysis error: {str(e)}"}), 500

@app.route('/analyze_like_status', methods=['POST'])
def analyze_like_status():
    return _analyze_social_action("like", LIKE_DETECTION_PROMPT, request.form, request.files)

@app.route('/analyze_comment_status', methods=['POST'])
def analyze_comment_status():
    return _analyze_social_action("comment", COMMENT_DETECTION_PROMPT, request.form, request.files)

@app.route('/analyze_share_status', methods=['POST'])
def analyze_share_status():
    return _analyze_social_action("share", SHARE_DETECTION_PROMPT, request.form, request.files)

@app.route('/analyze_subscribe_status', methods=['POST'])
def analyze_subscribe_status():
    return _analyze_social_action("subscribe", SUBSCRIBE_DETECTION_PROMPT, request.form, request.files)


@app.route('/advertisements/<int:ad_id>/click', methods=['POST'])
def click_advertisement(ad_id): # هذا لـ "نقر الرابط" وليس لإجراءات السوشيال ميديا
    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    data = request.get_json()
    clicking_user_id = data.get('user_id') 

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
        app.logger.info(f"User {clicking_user_id} already clicked Ad link {ad_id}. No new coins awarded to advertiser.")
        return jsonify({
            "message": "You have already interacted with this advertisement link.",
            "advertisement_id": ad_id,
            "number_of_clicks": advertisement.number_of_clicks
        }), 200

    advertiser = User.query.get(advertisement.user_id)
    if not advertiser:
        app.logger.error(f"CRITICAL: Advertiser (User ID {advertisement.user_id}) for Ad {ad_id} not found!")
        return jsonify({"error": "Internal server error: Advertiser not found"}), 500

    try:
        clicked_ids.append(clicking_user_id)
        advertisement.set_clicked_by_user_ids(clicked_ids)
        advertisement.number_of_clicks += 1
        
        coins_to_award_advertiser = advertisement.coin_per_click
        advertiser.coins += coins_to_award_advertiser
        
        advertisement.updated_at = datetime.utcnow()

        db.session.commit()
        app.logger.info(f"User {clicking_user_id} clicked Ad link {ad_id}. Advertiser {advertiser.id} awarded {coins_to_award_advertiser} coins. New balance: {advertiser.coins}")
        
        return jsonify({
            "message": "Advertisement link clicked successfully!",
            "advertisement_id": ad_id,
            "new_total_clicks_on_ad": advertisement.number_of_clicks,
            "coins_awarded_to_advertiser": coins_to_award_advertiser,
            "advertiser_new_coin_balance": advertiser.coins
        }), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error processing click on Ad link {ad_id} by User {clicking_user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error during click processing"}), 500

@app.route('/users/<int:user_id_param>', methods=['PATCH'])
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
        user.set_interests(data['interests']) # يجب أن تكون قائمة
        updated_fields.append('interests')
    if 'add_coins' in data: # هذه عملية إدارية، يجب تأمينها
        try:
            coins_to_add = int(data['add_coins'])
            if coins_to_add < 0: return jsonify({"error": "'add_coins' must be non-negative"}),400
            user.coins += coins_to_add
            updated_fields.append('coins_added')
        except (ValueError, TypeError): return jsonify({"error": "'add_coins' must be int"}),400
    if 'subtract_coins' in data: # هذه عملية إدارية، يجب تأمينها
        try:
            amount_to_subtract = int(data['subtract_coins'])
            if amount_to_subtract < 0: return jsonify({"error": "'subtract_coins' must be non-negative"}),400
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
@app.route('/admin/user_ad_actions', methods=['GET']) # تم إضافة /admin/ للدلالة على أنها للمشرف
def get_all_user_ad_actions():
    # !!! هام: يجب إضافة آلية تحقق من هوية المشرف هنا قبل تنفيذ هذا الكود !!!
    # على سبيل المثال، التحقق من توكن JWT أو دور المستخدم
    # if not current_user_is_admin():
    #     return jsonify({"error": "Unauthorized access. Admin privileges required."}), 403

    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int) # عدد السجلات في كل صفحة
        
        # فلترة اختيارية
        user_id_filter = request.args.get('user_id', type=int)
        ad_id_filter = request.args.get('advertisement_id', type=int)
        action_type_filter = request.args.get('action_type', type=str)

        query = UserAdAction.query

        if user_id_filter:
            query = query.filter(UserAdAction.user_id == user_id_filter)
        if ad_id_filter:
            query = query.filter(UserAdAction.advertisement_id == ad_id_filter)
        if action_type_filter:
            query = query.filter(UserAdAction.action_type.ilike(f"%{action_type_filter}%")) # بحث غير حساس لحالة الأحرف

        # الترتيب (يمكنك تغييره حسب الحاجة)
        actions_query = query.order_by(UserAdAction.created_at.desc())
        
        # التقسيم إلى صفحات (Pagination)
        paginated_actions = actions_query.paginate(page=page, per_page=per_page, error_out=False)
        
        actions_list = []
        for action in paginated_actions.items:
            actions_list.append({
                "id": action.id,
                "user_id": action.user_id,
                "advertisement_id": action.advertisement_id,
                "action_type": action.action_type,
                "created_at": action.created_at.isoformat() if action.created_at else None,
                # يمكنك إضافة معلومات عن المستخدم أو الإعلان إذا أردت (يتطلب join)
                # "user_email": action.user.email if action.user else None, 
                # "advertisement_title": action.advertisement.title if action.advertisement else None
            })
        
        return jsonify({
            "actions": actions_list,
            "total_actions": paginated_actions.total,
            "current_page": paginated_actions.page,
            "total_pages": paginated_actions.pages,
            "per_page": paginated_actions.per_page,
            "has_next": paginated_actions.has_next,
            "has_prev": paginated_actions.has_prev
        }), 200

    except Exception as e:
        app.logger.error(f"Error fetching all UserAdActions: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error fetching user ad actions"}), 500
@app.route('/users/<int:requesting_user_id>/advertisements/available_for_any_interaction', methods=['GET'])
def get_ads_available_for_any_interaction(requesting_user_id):
    user = User.query.get(requesting_user_id)
    if not user:
        return jsonify({"error": f"User with ID {requesting_user_id} not found."}), 404

    try:
        # 1. احصل على الإجراءات (مهام السوشيال ميديا) التي قام بها المستخدم
        actions_done_by_user_raw = db.session.query(
                                        UserAdAction.advertisement_id, 
                                        UserAdAction.action_type).filter(UserAdAction.user_id == requesting_user_id).all()
        
        # مجموعة بمعرفات الإعلانات التي قام المستخدم بأي مهمة سوشيال ميديا عليها
        ads_with_social_interaction_ids = {ad_id for ad_id, _ in actions_done_by_user_raw}
        app.logger.debug(f"User {requesting_user_id} has social interactions with ad_ids: {ads_with_social_interaction_ids}")

        # 2. احصل على جميع الإعلانات النشطة والموافق عليها
        #    (يمكنك إضافة فلتر لاستبعاد إعلانات المستخدم نفسه إذا أردت)
        query = Advertisement.query.filter(
            Advertisement.is_approved == True,
            Advertisement.is_active == True
            # Advertisement.user_id != requesting_user_id # اختياري
        )
        all_active_approved_ads = query.order_by(Advertisement.created_at.desc()).all()

        available_ads = []
        for ad in all_active_approved_ads:
            # 3. تحقق مما إذا كان المستخدم قد نقر على رابط هذا الإعلان
            users_who_clicked_this_ad_link = ad.get_clicked_by_user_ids()
            did_click_link = requesting_user_id in users_who_clicked_this_ad_link

            # 4. تحقق مما إذا كان المستخدم قد قام بأي مهمة سوشيال ميديا على هذا الإعلان
            did_social_interaction = ad.id in ads_with_social_interaction_ids
            
            # 5. إذا لم ينقر على الرابط ولم يقم بأي مهمة سوشيال ميديا، أضف الإعلان
            if not did_click_link and not did_social_interaction:
                available_ads.append(ad.to_dict())
        
        app.logger.info(f"Found {len(available_ads)} ads available for ANY interaction by user {requesting_user_id}.")
        return jsonify(available_ads), 200

    except Exception as e:
        app.logger.error(f"Error fetching ads available for any interaction for user {requesting_user_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500
# --- (مع بقية نقاط النهاية في ملف التطبيق) ---

# --- Coin Package Endpoints ---

@app.route('/admin/coin_packages', methods=['POST'])
def create_coin_package():
    # !!! هام: يجب إضافة آلية تحقق من هوية المشرف هنا !!!
    # if not current_user_is_admin():
    #     return jsonify({"error": "Unauthorized access. Admin privileges required."}), 403

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    data = request.get_json()
    name = data.get('name')
    amount_str = data.get('amount')
    price_usd_str = data.get('price_usd') # يمكن أن يكون null
    description = data.get('description')
    is_active = data.get('is_active', True) # افتراضيًا نشطة

    if not name or amount_str is None:
        return jsonify({"error": "Missing required fields: name, amount"}), 400

    try:
        amount = int(amount_str)
        if amount <= 0:
            return jsonify({"error": "Coin 'amount' must be a positive integer."}), 400
    except ValueError:
        return jsonify({"error": "'amount' must be a valid integer."}), 400

    price_usd = None
    if price_usd_str is not None:
        try:
            price_usd = float(price_usd_str)
            if price_usd < 0:
                return jsonify({"error": "'price_usd' must be a non-negative float."}), 400
        except ValueError:
            return jsonify({"error": "'price_usd' must be a valid float or null."}), 400

    if CoinPackage.query.filter_by(name=name).first():
        return jsonify({"error": f"Coin package with name '{name}' already exists."}), 409

    try:
        new_package = CoinPackage(
            name=name,
            amount=amount,
            price_usd=price_usd,
            description=description,
            is_active=is_active
        )
        db.session.add(new_package)
        db.session.commit()
        app.logger.info(f"Admin: New coin package created: {new_package.name}")
        return jsonify({"message": "Coin package created successfully", "package": new_package.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating coin package: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error creating coin package"}), 500


@app.route('/coin_packages', methods=['GET']) # نقطة نهاية عامة لعرض الباقات النشطة
def get_active_coin_packages():
    try:
        packages = CoinPackage.query.filter_by(is_active=True).order_by(CoinPackage.amount).all()
        return jsonify([pkg.to_dict() for pkg in packages]), 200
    except Exception as e:
        app.logger.error(f"Error fetching active coin packages: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/admin/coin_packages/all', methods=['GET']) # نقطة نهاية للمشرف لعرض كل الباقات (نشطة وغير نشطة)
def get_all_coin_packages_admin():
    # !!! هام: يجب إضافة آلية تحقق من هوية المشرف هنا !!!
    # if not current_user_is_admin():
    #     return jsonify({"error": "Unauthorized access. Admin privileges required."}), 403
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)
        
        paginated_packages = CoinPackage.query.order_by(CoinPackage.amount).paginate(page=page, per_page=per_page, error_out=False)
        
        packages_list = [pkg.to_dict() for pkg in paginated_packages.items]
        
        return jsonify({
            "packages": packages_list,
            "total_packages": paginated_packages.total,
            "current_page": paginated_packages.page,
            "total_pages": paginated_packages.pages
        }), 200
    except Exception as e:
        app.logger.error(f"Error fetching all coin packages for admin: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500


@app.route('/coin_packages/<int:package_id>', methods=['GET'])
def get_coin_package_by_id(package_id):
    try:
        package = CoinPackage.query.get(package_id)
        if package is None:
            return jsonify({"error": f"Coin package with ID {package_id} not found."}), 404
        # يمكنك إضافة شرط هنا للتحقق من is_active إذا كان المستخدم عاديًا
        # if not package.is_active and not current_user_is_admin(): # مثال
        #     return jsonify({"error": "Coin package not available."}), 404
        return jsonify(package.to_dict()), 200
    except Exception as e:
        app.logger.error(f"Error fetching coin package {package_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500


@app.route('/admin/coin_packages/<int:package_id>', methods=['PUT'])
def update_coin_package(package_id):
    # !!! هام: يجب إضافة آلية تحقق من هوية المشرف هنا !!!
    # if not current_user_is_admin():
    #     return jsonify({"error": "Unauthorized access. Admin privileges required."}), 403

    package = CoinPackage.query.get(package_id)
    if package is None:
        return jsonify({"error": f"Coin package with ID {package_id} not found."}), 404

    if not request.is_json:
        return jsonify({"error": "Request must be JSON"}), 400
    
    data = request.get_json()
    updated_fields = []

    if 'name' in data:
        new_name = data['name']
        if new_name != package.name and CoinPackage.query.filter_by(name=new_name).first():
            return jsonify({"error": f"Coin package name '{new_name}' already exists."}), 409
        package.name = new_name
        updated_fields.append('name')
    
    if 'amount' in data:
        try:
            amount = int(data['amount'])
            if amount <= 0:
                return jsonify({"error": "Coin 'amount' must be a positive integer."}), 400
            package.amount = amount
            updated_fields.append('amount')
        except ValueError:
            return jsonify({"error": "'amount' must be a valid integer."}), 400

    if 'price_usd' in data: # يسمح بتحديث السعر إلى null أيضًا
        price_usd_str = data['price_usd']
        if price_usd_str is None:
            package.price_usd = None
        else:
            try:
                price_usd = float(price_usd_str)
                if price_usd < 0:
                    return jsonify({"error": "'price_usd' must be a non-negative float."}), 400
                package.price_usd = price_usd
            except ValueError:
                return jsonify({"error": "'price_usd' must be a valid float or null."}), 400
        updated_fields.append('price_usd')

    if 'description' in data:
        package.description = data['description']
        updated_fields.append('description')
    
    if 'is_active' in data:
        if not isinstance(data['is_active'], bool):
            return jsonify({"error": "'is_active' must be a boolean."}), 400
        package.is_active = data['is_active']
        updated_fields.append('is_active')

    if not updated_fields:
        return jsonify({"message": "No valid fields provided for update."}), 200

    try:
        package.updated_at = datetime.utcnow()
        db.session.commit()
        app.logger.info(f"Admin: Coin package {package_id} updated. Fields: {', '.join(updated_fields)}")
        return jsonify({"message": "Coin package updated successfully", "package": package.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error updating coin package {package_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error updating coin package"}), 500
@app.route('/advertisements/approved', methods=['GET'])
def get_approved_advertisements():
    """
    نقطة نهاية مخصصة لجلب جميع الإعلانات الموافق عليها.
    تقبل بارامتر اختياري في الرابط 'exclude_user_id' لاستبعاد إعلانات مستخدم معين.
    مثال (بدون استبعاد): /advertisements/approved
    مثال (مع استبعاد):   /advertisements/approved?exclude_user_id=5
    """
    try:
        # 1. ابدأ بالاستعلام الأساسي: جلب كل الإعلانات التي is_approved = True
        query = Advertisement.query.filter_by(is_approved=True)
        
        # 2. تحقق من وجود البارامتر الاختياري 'exclude_user_id' في الرابط
        user_id_to_exclude_str = request.args.get('exclude_user_id')

        # 3. إذا كان البارامتر موجوداً، قم بتطبيقه كفلتر إضافي
        if user_id_to_exclude_str:
            try:
                # تأكد من أن القيمة رقمية لتجنب الأخطاء
                user_id_to_exclude = int(user_id_to_exclude_str)
                
                # أضف الشرط الجديد: حيث "user_id" لا يساوي (!=) الرقم المطلوب استبعاده
                query = query.filter(Advertisement.user_id != user_id_to_exclude)
                
                app.logger.info(f"Fetching approved ads, excluding those from user_id: {user_id_to_exclude}")

            except ValueError:
                app.logger.warning(f"Invalid 'exclude_user_id' provided: {user_id_to_exclude_str}")
                return jsonify({"error": "Invalid 'exclude_user_id'. It must be an integer."}), 400

        # 4. ترتيب النتائج من الأحدث إلى الأقدم وتنفيذ الاستعلام
        approved_ads = query.order_by(Advertisement.created_at.desc()).all()
        
        app.logger.info(f"Fetched {len(approved_ads)} approved advertisements after filtering.")
        
        # 5. تحويل النتائج إلى صيغة JSON وإرسالها
        return jsonify([ad.to_dict() for ad in approved_ads]), 200

    except Exception as e:
        app.logger.error(f"Error fetching approved advertisements: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error"}), 500
        
@app.route('/admin/coin_packages/<int:package_id>', methods=['DELETE'])
def delete_coin_package(package_id):
    # !!! هام: يجب إضافة آلية تحقق من هوية المشرف هنا !!!
    # if not current_user_is_admin():
    #     return jsonify({"error": "Unauthorized access. Admin privileges required."}), 403
    
    package = CoinPackage.query.get(package_id)
    if package is None:
        return jsonify({"error": f"Coin package with ID {package_id} not found"}), 404
    try:
        db.session.delete(package)
        db.session.commit()
        app.logger.info(f"Admin: Coin package {package_id} ({package.name}) deleted.")
        return jsonify({"message": f"Coin package {package_id} deleted successfully."}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting coin package {package_id}: {e}", exc_info=True)
        return jsonify({"error": "Internal Server Error deleting coin package"}), 500
# --- التشغيل المحلي ---
if __name__ == '__main__':
    print("Starting Flask development server (for local testing)...")
    app.run(host='0.0.0.0', port=5000)
