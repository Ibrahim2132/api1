# ... (Imports and App Setup remain the same) ...
import os
import json
import uuid
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# --- إعداد التطبيق وقاعدة البيانات ---
basedir = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
db = SQLAlchemy(app)


# --- جداول الربط للمفضلة ---

# جدول لربط المستخدمين بالإعلانات العامة المفضلة
user_favorite_advertisement = db.Table('user_favorite_advertisement',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('advertisement_id', db.Integer, db.ForeignKey('advertisement.id'), primary_key=True)
)

# جدول لربط المستخدمين بإعلانات السيارات المفضلة
user_favorite_car = db.Table('user_favorite_car',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('car_advertisement_id', db.Integer, db.ForeignKey('car_advertisement.id'), primary_key=True)
)

# جدول لربط المستخدمين بإعلانات العقارات المفضلة
user_favorite_real_estate = db.Table('user_favorite_real_estate',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('real_estate_advertisement_id', db.Integer, db.ForeignKey('real_estate_advertisement.id'), primary_key=True)
)


# --- تعريف موديل المستخدم (User Model) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    # is_admin = db.Column(db.Boolean, default=False, nullable=False)

    # علاقات الإعلانات المنشورة
    advertisements = db.relationship('Advertisement', backref='author', lazy='dynamic') # Changed to dynamic
    car_advertisements = db.relationship('CarAdvertisement', backref='author', lazy='dynamic') # Changed to dynamic
    real_estate_advertisements = db.relationship('RealEstateAdvertisement', backref='author', lazy='dynamic') # Changed to dynamic

    # --- علاقات المفضلة ---
    favorite_ads = db.relationship('Advertisement', secondary=user_favorite_advertisement,
                                   lazy='dynamic', # Use dynamic loading
                                   back_populates='favorited_by_users')
    favorite_car_ads = db.relationship('CarAdvertisement', secondary=user_favorite_car,
                                       lazy='dynamic',
                                       back_populates='favorited_by_users')
    favorite_real_estate_ads = db.relationship('RealEstateAdvertisement', secondary=user_favorite_real_estate,
                                             lazy='dynamic',
                                             back_populates='favorited_by_users')

    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    def to_dict(self): return {"id": self.id, "name": self.name, "phone_number": self.phone_number}
    def __repr__(self): return f'<User {self.name} - {self.phone_number}>'

# --- تعريف موديل الإعلان العام (Advertisement Model) ---
class Advertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # ... (other fields) ...
    category = db.Column(db.String(100), nullable=False); type = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=False); subcity = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String(200), nullable=False); description = db.Column(db.Text, nullable=False)
    phone_number = db.Column(db.String(20), nullable=False); price = db.Column(db.Float, nullable=False)
    images = db.Column(db.Text, nullable=True); user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    # --- علاقة عكسية للمستخدمين الذين فضلوا هذا الإعلان ---
    favorited_by_users = db.relationship('User', secondary=user_favorite_advertisement,
                                         lazy='dynamic', # Use dynamic loading
                                         back_populates='favorite_ads')

    def to_dict(self):
        image_list = json.loads(self.images) if self.images else []
        return {
            "id": self.id, "category": self.category, "type": self.type, "city": self.city,
            "subcity": self.subcity, "title": self.title, "description": self.description,
            "phone_number": self.phone_number, "price": self.price, "images": image_list,
            "user_id": self.user_id, "is_approved": self.is_approved
        }
    def __repr__(self): return f'<Advertisement {self.id} - {self.title} (Approved: {self.is_approved})>'


# --- تعريف موديل إعلان السيارة (CarAdvertisement Model) ---
class CarAdvertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # ... (other fields) ...
    city = db.Column(db.String(100), nullable=False); subcity = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String(200), nullable=False); description = db.Column(db.Text, nullable=False)
    phone_number = db.Column(db.String(20), nullable=False); price = db.Column(db.Float, nullable=False)
    images = db.Column(db.Text, nullable=True); user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    state = db.Column(db.String(50), nullable=False); car_category = db.Column(db.String(100), nullable=False)
    car_subcategory = db.Column(db.String(100), nullable=False); modelyear = db.Column(db.Integer, nullable=False)
    kilometer = db.Column(db.Integer, nullable=False); is_approved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    # --- علاقة عكسية للمستخدمين الذين فضلوا هذا الإعلان ---
    favorited_by_users = db.relationship('User', secondary=user_favorite_car,
                                         lazy='dynamic',
                                         back_populates='favorite_car_ads')

    def to_dict(self):
        image_list = json.loads(self.images) if self.images else []
        return {
            "id": self.id, "city": self.city, "subcity": self.subcity, "title": self.title,
            "description": self.description, "phone_number": self.phone_number,
            "price": self.price, "images": image_list, "user_id": self.user_id,
            "state": self.state, "car_category": self.car_category,
            "car_subcategory": self.car_subcategory, "modelyear": self.modelyear,
            "kilometer": self.kilometer, "is_approved": self.is_approved
        }
    def __repr__(self): return f'<CarAdvertisement {self.id} - {self.title} (Approved: {self.is_approved})>'


# --- تعريف موديل إعلان العقار (RealEstateAdvertisement Model) ---
class RealEstateAdvertisement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # ... (other fields) ...
    city = db.Column(db.String(100), nullable=False); subcity = db.Column(db.String(100), nullable=True)
    title = db.Column(db.String(200), nullable=False); description = db.Column(db.Text, nullable=False)
    phone_number = db.Column(db.String(20), nullable=False); price = db.Column(db.Float, nullable=False)
    images = db.Column(db.Text, nullable=True); user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(100), nullable=False); distance = db.Column(db.Float, nullable=True)
    num_bed = db.Column(db.Integer, nullable=False); num_bath = db.Column(db.Integer, nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False, index=True)
    # --- علاقة عكسية للمستخدمين الذين فضلوا هذا الإعلان ---
    favorited_by_users = db.relationship('User', secondary=user_favorite_real_estate,
                                         lazy='dynamic',
                                         back_populates='favorite_real_estate_ads')

    def to_dict(self):
        image_list = json.loads(self.images) if self.images else []
        return {
            "id": self.id, "city": self.city, "subcity": self.subcity, "title": self.title,
            "description": self.description, "phone_number": self.phone_number,
            "price": self.price, "images": image_list, "user_id": self.user_id,
            "type": self.type, "distance": self.distance, "num_bed": self.num_bed,
            "num_bath": self.num_bath, "is_approved": self.is_approved
        }
    def __repr__(self): return f'<RealEstateAdvertisement {self.id} - {self.title} (Approved: {self.is_approved})>'


# --- دالة مساعدة للتحقق من امتداد الملف ---
def allowed_file(filename):
    # ... (تبقى كما هي) ...
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- نقاط النهاية للمستخدمين (Register, Login, Get Profile) ---
# ... (تبقى كما هي) ...
@app.route('/register', methods=['POST'])
def register(): # ... (الكود كما هو)
    if not request.is_json: return jsonify({"error": "Missing JSON in request"}), 400
    data = request.get_json()
    name, password, phone_number = data.get('name'), data.get('password'), data.get('phone_number')
    if not name or not password or not phone_number: return jsonify({"error": "Missing required fields"}), 400
    if User.query.filter_by(phone_number=phone_number).first(): return jsonify({"error": "Phone number already registered"}), 409
    new_user = User(name=name, phone_number=phone_number)
    new_user.set_password(password)
    try: db.session.add(new_user); db.session.commit()
    except Exception as e: db.session.rollback(); app.logger.error(f"Reg Err: {e}"); return jsonify({"error":"ISE"}),500
    return jsonify({"message": "User registered successfully!", "user": new_user.to_dict()}), 201

@app.route('/login', methods=['POST'])
def login(): # ... (الكود كما هو)
    if not request.is_json: return jsonify({"error": "Missing JSON in request"}), 400
    data = request.get_json(); phone_number, password = data.get('phone_number'), data.get('password')
    if not phone_number or not password: return jsonify({"error": "Missing phone_number or password"}), 400
    user = User.query.filter_by(phone_number=phone_number).first()
    if user is None or not user.check_password(password): return jsonify({"error": "Invalid credentials"}), 401
    return jsonify({"message": "Login successful!", "user": user.to_dict()}), 200

@app.route('/user/<int:user_id>', methods=['GET'])
def get_user_profile(user_id): # ... (الكود كما هو)
    user = User.query.get_or_404(user_id)
    return jsonify({"user": user.to_dict()}), 200

# --- دوال مساعدة للإضافة والحفظ ورفع الصور ---
# ... ( _handle_image_upload, _save_entity تبقى كما هي) ...
def _handle_image_upload():
    uploaded_filenames = []
    if 'images' in request.files:
        image_files = request.files.getlist('images')
        for file in image_files:
            if file and file.filename != '' and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                unique_suffix = str(uuid.uuid4().hex)[:8]
                filename = f"{unique_suffix}_{original_filename}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                try: file.save(save_path); uploaded_filenames.append(filename)
                except Exception as e:
                    app.logger.error(f"Err saving {filename}: {e}")
                    for fname in uploaded_filenames:
                        try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                        except OSError: pass
                    return jsonify({"error": "Error saving images"}), 500
            elif file and file.filename != '': app.logger.warning(f"Skip disallowed: {file.filename}")
    return uploaded_filenames

def _save_entity(entity, uploaded_filenames):
    try:
        db.session.add(entity); db.session.commit()
        entity_type = entity.__class__.__name__.lower().replace("advertisement", "")
        if not entity_type or entity_type == "advertisement": entity_type = "advertisement"
        return jsonify({"message": f"{entity_type.replace('_',' ').capitalize()} submitted for approval!", "advertisement": entity.to_dict()}), 201
    except Exception as e:
        db.session.rollback(); app.logger.error(f"Err creating {entity.__class__.__name__}: {e}")
        for filename in uploaded_filenames:
            try: os.remove(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            except OSError: app.logger.error(f"Could not rm {filename} after db error.")
        return jsonify({"error": f"Internal error creating {entity_type}"}), 500

# --- نقاط النهاية لإضافة الإعلانات (POST) ---
# ... ( add_advertisement, add_car_advertisement, add_real_estate_advertisement تبقى كما هي ) ...
@app.route('/advertisements', methods=['POST'])
def add_advertisement():
    required=['user_id', 'category', 'type', 'city', 'title', 'description', 'phone_number', 'price']
    form=request.form; missing=[f for f in required if f not in form];
    if missing: return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    uid=form.get('user_id'); user=User.query.get(uid);
    if user is None: return jsonify({"error": f"User {uid} not found"}), 404
    try: price=float(form.get('price'))
    except: return jsonify({"error": "Invalid price"}), 400
    uploads=_handle_image_upload();
    if isinstance(uploads,tuple): return uploads
    new_ad = Advertisement(user_id=uid, category=form.get('category'), type=form.get('type'), city=form.get('city'), subcity=form.get('subcity'), title=form.get('title'), description=form.get('description'), phone_number=form.get('phone_number'), price=price, images=json.dumps(uploads) if uploads else None)
    return _save_entity(new_ad, uploads)
@app.route('/car_advertisements', methods=['POST'])
def add_car_advertisement():
    required=['user_id','city','title','description','phone_number','price','state','car_category','car_subcategory','modelyear','kilometer']
    form=request.form; missing=[f for f in required if f not in form];
    if missing: return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    uid=form.get('user_id'); user=User.query.get(uid);
    if user is None: return jsonify({"error": f"User {uid} not found"}), 404
    try: price=float(form.get('price'))
    except: return jsonify({"error": "Invalid price"}), 400
    try: modelyear=int(form.get('modelyear'))
    except: return jsonify({"error": "Invalid modelyear"}), 400
    try: km=int(form.get('kilometer'))
    except: return jsonify({"error": "Invalid kilometer"}), 400
    uploads=_handle_image_upload();
    if isinstance(uploads,tuple): return uploads
    new_car=CarAdvertisement(user_id=uid,city=form.get('city'),subcity=form.get('subcity'),title=form.get('title'),description=form.get('description'),phone_number=form.get('phone_number'),price=price,images=json.dumps(uploads) if uploads else None,state=form.get('state'),car_category=form.get('car_category'),car_subcategory=form.get('car_subcategory'),modelyear=modelyear,kilometer=km)
    return _save_entity(new_car, uploads)
@app.route('/real_estate_advertisements', methods=['POST'])
def add_real_estate_advertisement():
    required=['user_id','city','title','description','phone_number','price','type','num_bed','num_bath']
    form=request.form; missing=[f for f in required if f not in form];
    if missing: return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    uid=form.get('user_id'); user=User.query.get(uid);
    if user is None: return jsonify({"error": f"User {uid} not found"}), 404
    try: price=float(form.get('price'))
    except: return jsonify({"error": "Invalid price"}), 400
    try: beds=int(form.get('num_bed'))
    except: return jsonify({"error": "Invalid num_bed"}), 400
    try: baths=int(form.get('num_bath'))
    except: return jsonify({"error": "Invalid num_bath"}), 400
    dist=None; dist_str=form.get('distance')
    if dist_str:
        try: dist=float(dist_str)
        except: return jsonify({"error": "Invalid distance"}), 400
    uploads=_handle_image_upload();
    if isinstance(uploads,tuple): return uploads
    new_re=RealEstateAdvertisement(user_id=uid,city=form.get('city'),subcity=form.get('subcity'),title=form.get('title'),description=form.get('description'),phone_number=form.get('phone_number'),price=price,images=json.dumps(uploads) if uploads else None,type=form.get('type'),distance=dist,num_bed=beds,num_bath=baths)
    return _save_entity(new_re, uploads)

# === نقاط النهاية لجلب الإعلانات للمستخدم (فقط الموافق عليها) ===
# ... ( /advertisements/all, /car_advertisements/all, /real_estate_advertisements/all تبقى كما هي مع فلتر is_approved=True ) ...
@app.route('/advertisements/all', methods=['GET'])
def get_all_advertisements():
    try: ads = Advertisement.query.filter_by(is_approved=True).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch approved ads: {e}"); return jsonify({"error":"ISE"}),500
    return jsonify(result), 200
@app.route('/car_advertisements/all', methods=['GET'])
def get_all_car_advertisements():
    try: ads = CarAdvertisement.query.filter_by(is_approved=True).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch approved car ads: {e}"); return jsonify({"error":"ISE"}),500
    return jsonify(result), 200
@app.route('/real_estate_advertisements/all', methods=['GET'])
def get_all_real_estate_advertisements():
    try: ads = RealEstateAdvertisement.query.filter_by(is_approved=True).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch approved re ads: {e}"); return jsonify({"error":"ISE"}),500
    return jsonify(result), 200

# === نقاط نهاية جديدة خاصة بـ Admin ===
# ... ( /admin/.../pending, /admin/.../approve تبقى كما هي ) ...
@app.route('/admin/advertisements/pending', methods=['GET'])
def admin_get_pending_advertisements(): # Add admin auth check
    try: ads = Advertisement.query.filter_by(is_approved=False).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch pending ads: {e}"); return jsonify({"error":"ISE"}),500
    return jsonify(result), 200
@app.route('/admin/car_advertisements/pending', methods=['GET'])
def admin_get_pending_car_advertisements(): # Add admin auth check
    try: ads = CarAdvertisement.query.filter_by(is_approved=False).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch pending car ads: {e}"); return jsonify({"error":"ISE"}),500
    return jsonify(result), 200
@app.route('/admin/real_estate_advertisements/pending', methods=['GET'])
def admin_get_pending_real_estate_advertisements(): # Add admin auth check
    try: ads = RealEstateAdvertisement.query.filter_by(is_approved=False).all(); result = [ad.to_dict() for ad in ads]
    except Exception as e: app.logger.error(f"Err fetch pending re ads: {e}"); return jsonify({"error":"ISE"}),500
    return jsonify(result), 200
@app.route('/admin/advertisements/<int:ad_id>/approve', methods=['PUT'])
def admin_approve_advertisement(ad_id): # Add admin auth check
    ad = Advertisement.query.get_or_404(ad_id);
    if ad.is_approved: return jsonify({"message": "Already approved."}), 200
    ad.is_approved = True;
    try: db.session.commit(); return jsonify({"message": f"Ad {ad_id} approved.", "advertisement": ad.to_dict()}), 200
    except Exception as e: db.session.rollback(); app.logger.error(f"Err approve ad {ad_id}: {e}"); return jsonify({"error":"ISE"}),500
@app.route('/admin/car_advertisements/<int:ad_id>/approve', methods=['PUT'])
def admin_approve_car_advertisement(ad_id): # Add admin auth check
    ad = CarAdvertisement.query.get_or_404(ad_id);
    if ad.is_approved: return jsonify({"message": "Already approved."}), 200
    ad.is_approved = True;
    try: db.session.commit(); return jsonify({"message": f"Car Ad {ad_id} approved.", "advertisement": ad.to_dict()}), 200
    except Exception as e: db.session.rollback(); app.logger.error(f"Err approve car ad {ad_id}: {e}"); return jsonify({"error":"ISE"}),500
@app.route('/admin/real_estate_advertisements/<int:ad_id>/approve', methods=['PUT'])
def admin_approve_real_estate_advertisement(ad_id): # Add admin auth check
    ad = RealEstateAdvertisement.query.get_or_404(ad_id);
    if ad.is_approved: return jsonify({"message": "Already approved."}), 200
    ad.is_approved = True;
    try: db.session.commit(); return jsonify({"message": f"RE Ad {ad_id} approved.", "advertisement": ad.to_dict()}), 200
    except Exception as e: db.session.rollback(); app.logger.error(f"Err approve re ad {ad_id}: {e}"); return jsonify({"error":"ISE"}),500


# === نقاط نهاية جديدة خاصة بالمفضلة ===

# --- إضافة إعلان عام للمفضلة ---
@app.route('/user/<int:user_id>/favorites/advertisements/<int:ad_id>', methods=['POST'])
def add_ad_to_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = Advertisement.query.get_or_404(ad_id)
    # تحقق مما إذا كان الإعلان مضافاً بالفعل للمفضلة
    if ad in user.favorite_ads:
         return jsonify({"message": "Advertisement already in favorites."}), 200 # أو 409 Conflict
    user.favorite_ads.append(ad)
    try:
        db.session.commit()
        return jsonify({"message": "Advertisement added to favorites successfully."}), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding ad {ad_id} to user {user_id} favorites: {e}")
        return jsonify({"error": "Internal server error adding favorite"}), 500

# --- إضافة إعلان سيارة للمفضلة ---
@app.route('/user/<int:user_id>/favorites/cars/<int:ad_id>', methods=['POST'])
def add_car_ad_to_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = CarAdvertisement.query.get_or_404(ad_id)
    if ad in user.favorite_car_ads:
         return jsonify({"message": "Car advertisement already in favorites."}), 200
    user.favorite_car_ads.append(ad)
    try:
        db.session.commit()
        return jsonify({"message": "Car advertisement added to favorites successfully."}), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding car ad {ad_id} to user {user_id} fav: {e}")
        return jsonify({"error": "Internal server error adding favorite"}), 500

# --- إضافة إعلان عقار للمفضلة ---
@app.route('/user/<int:user_id>/favorites/real_estate/<int:ad_id>', methods=['POST'])
def add_real_estate_ad_to_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = RealEstateAdvertisement.query.get_or_404(ad_id)
    if ad in user.favorite_real_estate_ads:
         return jsonify({"message": "Real estate advertisement already in favorites."}), 200
    user.favorite_real_estate_ads.append(ad)
    try:
        db.session.commit()
        return jsonify({"message": "Real estate advertisement added to favorites successfully."}), 201
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error adding re ad {ad_id} to user {user_id} fav: {e}")
        return jsonify({"error": "Internal server error adding favorite"}), 500

# --- إزالة إعلان عام من المفضلة ---
@app.route('/user/<int:user_id>/favorites/advertisements/<int:ad_id>', methods=['DELETE'])
def remove_ad_from_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = Advertisement.query.get_or_404(ad_id)
    if ad not in user.favorite_ads:
         return jsonify({"error": "Advertisement not found in favorites."}), 404
    user.favorite_ads.remove(ad)
    try:
        db.session.commit()
        # 204 No Content مناسبة لعمليات الحذف الناجحة التي لا ترجع محتوى
        return '', 204
        # أو يمكنك إرجاع رسالة:
        # return jsonify({"message": "Advertisement removed from favorites."}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error removing ad {ad_id} from user {user_id} favorites: {e}")
        return jsonify({"error": "Internal server error removing favorite"}), 500

# --- إزالة إعلان سيارة من المفضلة ---
@app.route('/user/<int:user_id>/favorites/cars/<int:ad_id>', methods=['DELETE'])
def remove_car_ad_from_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = CarAdvertisement.query.get_or_404(ad_id)
    if ad not in user.favorite_car_ads:
         return jsonify({"error": "Car advertisement not found in favorites."}), 404
    user.favorite_car_ads.remove(ad)
    try:
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error removing car ad {ad_id} from user {user_id} fav: {e}")
        return jsonify({"error": "Internal server error removing favorite"}), 500

# --- إزالة إعلان عقار من المفضلة ---
@app.route('/user/<int:user_id>/favorites/real_estate/<int:ad_id>', methods=['DELETE'])
def remove_real_estate_ad_from_favorites(user_id, ad_id):
    user = User.query.get_or_404(user_id)
    ad = RealEstateAdvertisement.query.get_or_404(ad_id)
    if ad not in user.favorite_real_estate_ads:
         return jsonify({"error": "Real estate advertisement not found in favorites."}), 404
    user.favorite_real_estate_ads.remove(ad)
    try:
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error removing re ad {ad_id} from user {user_id} fav: {e}")
        return jsonify({"error": "Internal server error removing favorite"}), 500


# --- جلب كل مفضلات المستخدم ---
@app.route('/user/<int:user_id>/favorites', methods=['GET'])
def get_user_favorites(user_id):
    user = User.query.get_or_404(user_id)
    try:
        # جلب كل الإعلانات المفضلة وتحويلها
        # لاحظ استخدام .all() هنا لأننا نريد النتائج الفعلية الآن
        fav_ads = [ad.to_dict() for ad in user.favorite_ads.filter(Advertisement.is_approved==True).all()] # Only approved
        fav_car_ads = [ad.to_dict() for ad in user.favorite_car_ads.filter(CarAdvertisement.is_approved==True).all()] # Only approved
        fav_re_ads = [ad.to_dict() for ad in user.favorite_real_estate_ads.filter(RealEstateAdvertisement.is_approved==True).all()] # Only approved

        # تجميع النتائج في قاموس واحد
        all_favorites = {
            "advertisements": fav_ads,
            "car_advertisements": fav_car_ads,
            "real_estate_advertisements": fav_re_ads
        }
        return jsonify(all_favorites), 200
    except Exception as e:
        app.logger.error(f"Error fetching favorites for user {user_id}: {e}")
        return jsonify({"error": "Internal server error fetching favorites"}), 500


# --- تشغيل السيرفر ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all() # سينشئ جداول الربط للمفضلة أيضًا
        print("Database tables checked/created.")
    app.run(debug=True, host='0.0.0.0', port=5000)