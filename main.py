from fastapi import FastAPI, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from pydantic import BaseModel
import jwt
from datetime import datetime, timedelta
import logging

from models import async_session, User, init_db, close_db


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=30)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_db():
    db = async_session()
    try:
        yield db
    finally:
        await db.close()


class UserCreateUpdate(BaseModel):
    username: str
    email: str
    password: str


class UserOutput(UserCreateUpdate):
    id: int


@app.on_event("startup")
async def startup_event():
    await init_db()


@app.on_event("shutdown")
async def shutdown_event():
    await close_db()


@app.post("/users/", response_model=UserOutput)
async def create_user(user: UserCreateUpdate, db: Session = Depends(get_db)):
    hashed_password = pwd_context.hash(user.password)
    db_user = User(**user, password=hashed_password)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user


@app.get("/users/{user_id}", response_model=UserOutput)
async def get_user(user_id: int, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="NOT FOUND")
    return db_user


@app.get("/users/", response_model=list[UserOutput])
async def get_all_users(
    skip: int = Query(0, alias="page",
                      discription="Skip records (pagination)"),
    limit: int = Query(10, description="Limit the number of records to fetch"),
    db: Session = Depends(get_db)
):
    users = await db.query(User).offset(skip).limit(limit).all()
    return users


@app.put("/users/{user_id}", response_model=UserOutput)
async def update_user(user_id: int,
                      user: UserCreateUpdate, db: Session = Depends(get_db)):
    db_user = await db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="NOT FOUND")
    for key, value in user.items():
        setattr(db_user, key, value)
    await db.commit()
    await db.refresh(db_user)
    return db_user


@app.delete("/users/{user_id}", response_model=UserOutput)
async def delete_user(user_id: int, db: Session = Depends(get_db)):
    db_user = await db.query(User).filter(User.id == user_id).first()
    if db_user is None:
        raise HTTPException(status_code=404, detail="NOT FOUND")
    db.delete(db_user)
    await db.commit()
    return db_user


@app.post("/token/")
async def login_for_access_token(db: Session = Depends(get_db),
                                 user_data: UserCreateUpdate = Depends()):
    db_user = await db.query(User).filter(
        User.username == user_data.username
    ).first()
    if db_user is None or not pwd_context.verify(user_data.password,
                                                 db_user.password):
        raise HTTPException(status_code=400, detail="Incorrect")
    access_token_expires = timedelta(minutes=30)
    access_token = create_access_token(
        data={"sub": db_user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("users/filter/")
async def filter_users(
    username: str = Query(None, description="Filter by username"),
    email: str = Query(None, description="Filter by email"),
    sort_by: str = Query("id",
                         description="Sort by filed (e.g., 'id', 'username')"),
    order: str = Query("asc", description="Sort order (asc or desc)"),
    db: Session = Depends(get_db)
):
    query = await db.query(User)
    if username:
        query = query.filter(User.username == username)
    if email:
        query = query.filter(User.email == email)
    if order == "desc":
        query = query.order_by(getattr(User, sort_by).desc())
    else:
        query = query.order_by(getattr(User, sort_by))
    users = await query.all
    return users
