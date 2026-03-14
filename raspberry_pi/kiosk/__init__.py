"""
Kiosk Module for Project Spotless
"""
from .web_server import create_app, socketio

__all__ = ['create_app', 'socketio']
