"""A tiny 'host' application that uses the Statement Analyser as a module.

Run from the backend folder:   pip install -e . uvicorn   then   uvicorn host_app:host --app-dir ../examples --port 9000
Then open  http://localhost:9000/statement-analyser/docs  (the module's API docs) and try /hello.
"""
from fastapi import FastAPI

from statement_analyser import mount

host = FastAPI(title="Host application")


@host.get("/hello")
def hello():
    return {"message": "This is the host app. The Statement Analyser lives under /statement-analyser."}


# One line adds the whole module. db_path is where it keeps saved statements.
mount(host, prefix="/statement-analyser", db_path="data/statement_analyser.db")
