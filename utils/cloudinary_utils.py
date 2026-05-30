import cloudinary
import cloudinary.uploader
from config import Config


def init_cloudinary():
    cloudinary.config(
        cloud_name=Config.CLOUDINARY_CLOUD_NAME,
        api_key=Config.CLOUDINARY_API_KEY,
        api_secret=Config.CLOUDINARY_API_SECRET,
        secure=True,
    )


def upload_image(file, folder="event_management"):
    init_cloudinary()
    result = cloudinary.uploader.upload(
        file,
        folder=folder,
        resource_type="image",
    )
    return result.get("secure_url")


def delete_image(public_id):
    init_cloudinary()
    cloudinary.uploader.destroy(public_id)
