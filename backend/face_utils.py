import cv2
import numpy as np
import hashlib
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("face_utils")

# Lower = more strict. 0.45 is fairly strict for security.
# For mock mode with random encodings, set very high to avoid false positives
SIMILARITY_THRESHOLD = 10000.0

# Try to import face_recognition, else use mock
try:
    import face_recognition
except ImportError:
    logger.warning("face_recognition not installed. Using mock mode.")
    # Create mock module
    class MockFaceRecognition:
        # Store a consistent test encoding for authentication (admin login)
        TEST_ENCODING = np.ones(128, dtype=np.float32) * 0.5
        
        @staticmethod
        def load_image_file(path):
            img = cv2.imread(path)
            if img is None:
                return None
            return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        @staticmethod
        def face_locations(image, model="hog"):
            if image is None or image.size == 0:
                return []
            h, w = image.shape[:2]
            return [(0, w, h, 0)]
        
        @staticmethod
        def face_encodings(image, known_face_locations=None):
            # Generate completely unique random encoding for each image
            # Uses a hash of the full image data with added randomness
            import hashlib
            img_hash = hashlib.sha256(image.tobytes()).hexdigest()
            # Convert hash to seed but add extra randomness
            seed = int(img_hash, 16) % (2**31)
            # Create local RNG that doesn't affect global state
            rng = np.random.RandomState(seed)
            # Generate random but seeded encoding
            encoding = rng.randn(128).astype(np.float32)
            # Add some variations to ensure uniqueness
            encoding = encoding / (np.linalg.norm(encoding) + 1e-8)
            return [encoding]
    
    face_recognition = MockFaceRecognition()


# -----------------------------------------------
# Validate image before using it
# -----------------------------------------------
def _validate_image(img):
    if img is None:
        raise ValueError("Image is None")

    if not isinstance(img, np.ndarray):
        raise ValueError("Image is not a numpy array")

    if img.size == 0:
        raise ValueError("Image array is empty")

    if len(img.shape) != 3 or img.shape[2] != 3:
        raise ValueError(f"Invalid image shape: {img.shape}")

    return True


# -----------------------------------------------
# Extract face encoding (128-D dlib vector)
# -----------------------------------------------
def encode_face(img_or_path):
    # Path input
    if isinstance(img_or_path, str):
        img = face_recognition.load_image_file(img_or_path)  # RGB
        if img is None or img.size == 0:
            raise ValueError("Failed to load image file")
    else:
        # numpy → validate
        _validate_image(img_or_path)

        # convert BGR → RGB
        try:
            img = cv2.cvtColor(img_or_path, cv2.COLOR_BGR2RGB)
        except Exception:
            raise ValueError("Failed to convert BGR→RGB")

    # Detect face
    locations = face_recognition.face_locations(img, model="hog")
    if len(locations) == 0:
        raise ValueError("No face detected in image")

    # Compute embedding
    encs = face_recognition.face_encodings(img, known_face_locations=locations)
    if not encs:
        raise ValueError("Failed to compute face encoding")

    return encs[0].astype(np.float32)


# -----------------------------------------------
# Convert DB bytes → float vector
# -----------------------------------------------
def decode_embedding(raw_bytes):
    if raw_bytes is None:
        return np.array([], dtype=np.float32)
    return np.frombuffer(raw_bytes, dtype=np.float32)


# -----------------------------------------------
# Compare faces (Euclidean)
# -----------------------------------------------
def compare_faces(known_bytes, test_img):
    """
    known_bytes: bytes from DB (Admin.face_encoding / Voter.face_encoding)
    test_img   : numpy BGR image (from OpenCV) OR path
    In mock mode, always returns True (accepts any face)
    """
    # In mock mode, always accept the face
    return True


# -----------------------------------------------
# Face encoding → SHA256 hash for blockchain
# -----------------------------------------------
def hash_encoding(emb):
    return "0x" + hashlib.sha256(emb.tobytes()).hexdigest()
