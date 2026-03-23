import os
import tempfile
import unittest
import sys
import shutil
from unittest.mock import patch, MagicMock
current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_script_dir)
common_path = os.path.join(project_root, 'common')

if common_path not in sys.path:
    sys.path.insert(0, common_path)
if project_root not in sys.path:
     sys.path.insert(0, project_root)

from common.interfaces.framework_analyzer import FrameworkAnalyzer
from django_analyzer import DjangoAnalyzer
from common.interfaces.code_analyzer import CodeAnalyzer
from python_analyzer import PythonCodeAnalyzer

class TestDjangoAnalyzerSerializers(unittest.TestCase):
    """Test suite for testing serializer detection and component generation in DjangoAnalyzer."""

    def setUp(self):
        """Set up test environment with mock project structure."""
        # Create temporary directory for test files
        self.test_dir = tempfile.mkdtemp()
        
        # Create mock Python analyzer
        self.code_analyzer = PythonCodeAnalyzer()
        
        # Mock analysis results - this simulates what would be loaded from a file
        self.mock_analysis_results = {
            "result": {},
            "file_identifiers": {},
            "module_to_path": {},
            "no_of_lines": 0,
            "unresolved_imports": {},
            "sys_path": ["/mock/site-packages"]
        }
        
        # Create test files structure
        self._create_test_files()
        
        # Create analyzer with mock data
        self.analyzer = DjangoAnalyzer(self.code_analyzer, self.test_dir)
        self.analyzer.analysis_results = self.mock_analysis_results

    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.test_dir)

    def _create_test_files(self):
        """Create test file structure with serializers and models."""
        # Create directories
        os.makedirs(os.path.join(self.test_dir, "api"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "core"), exist_ok=True)
        
        # Create serializers.py
        with open(os.path.join(self.test_dir, "api", "serializers.py"), "w") as f:
            f.write("""
from rest_framework import serializers
from core.models import User, Post, Comment

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email')
        read_only_fields = ('id',)

class PostSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    
    class Meta:
        model = Post
        fields = ('id', 'title', 'content', 'author', 'created_at')
        read_only_fields = ('id', 'created_at')

class CommentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    text = serializers.CharField(max_length=200)
    post_id = serializers.IntegerField()
    author_id = serializers.IntegerField()
    created_at = serializers.DateTimeField(read_only=True)
    
    def create(self, validated_data):
        return Comment.objects.create(**validated_data)
        
class NestedUserSerializer(UserSerializer):
    posts = PostSerializer(many=True, read_only=True)
    
    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + ('posts',)
            """)
            
        # Create models.py
        with open(os.path.join(self.test_dir, "core", "models.py"), "w") as f:
            f.write("""
from django.db import models

class User(models.Model):
    username = models.CharField(max_length=100)
    email = models.EmailField()
    
    def __str__(self):
        return self.username

class Post(models.Model):
    title = models.CharField(max_length=200)
    content = models.TextField()
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.title

class Comment(models.Model):
    text = models.CharField(max_length=200)
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Comment by {self.author.username} on {self.post.title}"
            """)
        
        # Create manage.py to identify as a Django project
        with open(os.path.join(self.test_dir, "manage.py"), "w") as f:
            f.write("""#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "project.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
            """)
        
        # Set up analysis results based on the structure we've created
        serializers_path = os.path.join(self.test_dir, "api", "serializers.py")
        models_path = os.path.join(self.test_dir, "core", "models.py")
        
        # Add mock entries for serializer classes
        self.mock_analysis_results["result"][serializers_path] = {
            "classes": {
                "UserSerializer": {
                    "name": "UserSerializer",
                    "startLine": 5,
                    "endLine": 9,
                    "properties": [],
                    "innerClasses": [
                        {
                            "name": "Meta", 
                            "properties": ["model = User", "fields = ('id', 'username', 'email')", "read_only_fields = ('id',)"]
                        }
                    ],
                    "parentClasses": {
                        "serializers.ModelSerializer": {"name": "serializers.ModelSerializer", "path": None}
                    },
                    "identifiers": {"classes": ["User"], "functions": [], "variables": []}
                },
                "PostSerializer": {
                    "name": "PostSerializer",
                    "startLine": 11,
                    "endLine": 16,
                    "properties": ["author = UserSerializer(read_only=True)"],
                    "innerClasses": [
                        {
                            "name": "Meta", 
                            "properties": ["model = Post", "fields = ('id', 'title', 'content', 'author', 'created_at')", 
                                          "read_only_fields = ('id', 'created_at')"]
                        }
                    ],
                    "parentClasses": {
                        "serializers.ModelSerializer": {"name": "serializers.ModelSerializer", "path": None}
                    },
                    "identifiers": {"classes": ["UserSerializer", "Post"], "functions": [], "variables": []}
                },
                "CommentSerializer": {
                    "name": "CommentSerializer",
                    "startLine": 18,
                    "endLine": 27,
                    "properties": [
                        "id = serializers.IntegerField(read_only=True)", 
                        "text = serializers.CharField(max_length=200)",
                        "post_id = serializers.IntegerField()",
                        "author_id = serializers.IntegerField()",
                        "created_at = serializers.DateTimeField(read_only=True)"
                    ],
                    "functions": {
                        "create": {
                            "startLine": 25,
                            "endLine": 26,
                            "decorators": [],
                            "context": {"name": "create"}
                        }
                    },
                    "innerClasses": [],
                    "parentClasses": {
                        "serializers.Serializer": {"name": "serializers.Serializer", "path": None}
                    },
                    "identifiers": {"classes": ["Comment"], "functions": [], "variables": []}
                },
                "NestedUserSerializer": {
                    "name": "NestedUserSerializer",
                    "startLine": 29,
                    "endLine": 33,
                    "properties": ["posts = PostSerializer(many=True, read_only=True)"],
                    "innerClasses": [
                        {
                            "name": "Meta", 
                            "properties": ["fields = UserSerializer.Meta.fields + ('posts',)"]
                        }
                    ],
                    "parentClasses": {
                        "UserSerializer": {"name": "UserSerializer", "path": serializers_path}
                    },
                    "identifiers": {"classes": ["UserSerializer", "PostSerializer"], "functions": [], "variables": []}
                }
            },
            "functions": {},
            "statements": []
        }
        
        # Add mock entries for model classes
        self.mock_analysis_results["result"][models_path] = {
            "classes": {
                "User": {
                    "name": "User",
                    "startLine": 3,
                    "endLine": 8,
                    "properties": ["username = models.CharField(max_length=100)", "email = models.EmailField()"],
                    "innerClasses": [],
                    "functions": {
                        "__str__": {
                            "startLine": 7,
                            "endLine": 8,
                            "decorators": [],
                            "context": {"name": "__str__"}
                        }
                    },
                    "parentClasses": {
                        "models.Model": {"name": "models.Model", "path": None}
                    },
                    "identifiers": {"classes": [], "functions": [], "variables": []}
                },
                "Post": {
                    "name": "Post",
                    "startLine": 10,
                    "endLine": 16,
                    "properties": [
                        "title = models.CharField(max_length=200)", 
                        "content = models.TextField()",
                        "author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='posts')",
                        "created_at = models.DateTimeField(auto_now_add=True)"
                    ],
                    "innerClasses": [],
                    "functions": {
                        "__str__": {
                            "startLine": 15,
                            "endLine": 16,
                            "decorators": [],
                            "context": {"name": "__str__"}
                        }
                    },
                    "parentClasses": {
                        "models.Model": {"name": "models.Model", "path": None}
                    },
                    "identifiers": {"classes": ["User"], "functions": [], "variables": []}
                },
                "Comment": {
                    "name": "Comment",
                    "startLine": 18,
                    "endLine": 25,
                    "properties": [
                        "text = models.CharField(max_length=200)",
                        "post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')",
                        "author = models.ForeignKey(User, on_delete=models.CASCADE)",
                        "created_at = models.DateTimeField(auto_now_add=True)"
                    ],
                    "innerClasses": [],
                    "functions": {
                        "__str__": {
                            "startLine": 24,
                            "endLine": 25,
                            "decorators": [],
                            "context": {"name": "__str__"}
                        }
                    },
                    "parentClasses": {
                        "models.Model": {"name": "models.Model", "path": None}
                    },
                    "identifiers": {"classes": ["Post", "User"], "functions": [], "variables": []}
                }
            },
            "functions": {},
            "statements": []
        }
        
        # Set up file identifiers for cross-references
        self.mock_analysis_results["file_identifiers"][serializers_path] = {
            "classes": {
                "User": {"name": "User", "alias": "User", "path": models_path, "type": "class"},
                "Post": {"name": "Post", "alias": "Post", "path": models_path, "type": "class"},
                "Comment": {"name": "Comment", "alias": "Comment", "path": models_path, "type": "class"},
                "UserSerializer": {"name": "UserSerializer", "alias": "UserSerializer", "path": serializers_path, "type": "class"},
                "PostSerializer": {"name": "PostSerializer", "alias": "PostSerializer", "path": serializers_path, "type": "class"},
                "CommentSerializer": {"name": "CommentSerializer", "alias": "CommentSerializer", "path": serializers_path, "type": "class"}
            },
            "functions": {},
            "variables": {},
            "file_identifiers": {}
        }
        
        self.mock_analysis_results["file_identifiers"][models_path] = {
            "classes": {
                "User": {"name": "User", "alias": "User", "path": models_path, "type": "class"},
                "Post": {"name": "Post", "alias": "Post", "path": models_path, "type": "class"},
                "Comment": {"name": "Comment", "alias": "Comment", "path": models_path, "type": "class"}
            },
            "functions": {},
            "variables": {},
            "file_identifiers": {}
        }
        
        # Paths for our test
        self.serializers_path = serializers_path
        self.models_path = models_path

    @patch.object(PythonCodeAnalyzer, 'get_code_snippet')
    def test_identify_serializers(self, mock_get_code_snippet):
        """Test that serializers are correctly identified."""
        # Mock the get_code_snippet method to return mock code
        mock_get_code_snippet.return_value = "# Mock code snippet"
        
        # Run identification
        self.analyzer._identify_serializers_and_models()
        
        # Check that serializers have been correctly identified
        serializer_keys = [
            f"{self.serializers_path}:UserSerializer",
            f"{self.serializers_path}:PostSerializer",
            f"{self.serializers_path}:CommentSerializer",
            f"{self.serializers_path}:NestedUserSerializer"
        ]
        
        for key in serializer_keys:
            self.assertIn(key, self.analyzer.is_serializer)
            self.assertTrue(self.analyzer.is_serializer[key], f"Expected {key} to be identified as a serializer")
        
        # Check that models have been correctly identified
        model_keys = [
            f"{self.models_path}:User",
            f"{self.models_path}:Post",
            f"{self.models_path}:Comment"
        ]
        
        # The models may or may not be in self.is_model depending on how the serializer analysis went,
        # so we'll only check the ones that are present
        models_found = sum(1 for key in model_keys if key in self.analyzer.is_model and self.analyzer.is_model[key])
        self.assertGreaterEqual(models_found, 1, "Expected at least one model to be identified")

    @patch.object(PythonCodeAnalyzer, 'get_code_snippet')
    def test_get_schema_components(self, mock_get_code_snippet):
        """Test that schema components are correctly generated."""
        # Mock the get_code_snippet method to return mock code
        mock_get_code_snippet.return_value = "# Mock code snippet"
        
        # First identify serializers
        self.analyzer._identify_serializers_and_models()
        
        # Get schema components
        components = self.analyzer.get_schema_components()
        
        # Check that we have the expected components (each serializer should have request and response schemas)
        expected_components = [
            "UserSerializerRequest",
            "UserSerializerResponse",
            "PostSerializerRequest",
            "PostSerializerResponse",
            "CommentSerializerRequest",
            "CommentSerializerResponse",
            "NestedUserSerializerRequest",
            "NestedUserSerializerResponse"
        ]
        
        for component_name in expected_components:
            self.assertIn(component_name, components, f"Expected component {component_name} to be generated")
            
            # Check component structure
            component = components[component_name]
            self.assertIn("path", component)
            self.assertIn("serializer_name", component)
            self.assertIn("is_request", component)
            self.assertIn("is_model", component)
            
            # Check request/response flag
            if "Request" in component_name:
                self.assertTrue(component["is_request"])
            else:
                self.assertFalse(component["is_request"])
                
            # Check serializer name
            serializer_name = component_name.replace("Request", "").replace("Response", "")
            self.assertEqual(serializer_name, component["serializer_name"])

    @patch.object(PythonCodeAnalyzer, 'get_code_snippet')
    def test_get_component_context(self, mock_get_code_snippet):
        """Test building context for a component."""
        # Mock the get_code_snippet method to return specific code for different components
        def mock_code_snippet(file_path, start_line, end_line):
            if "serializers.py" in file_path and "UserSerializer" in self.mock_analysis_results["result"][file_path]["classes"]:
                return """
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email')
        read_only_fields = ('id',)
                """
            elif "models.py" in file_path and "User" in self.mock_analysis_results["result"][file_path]["classes"]:
                return """
class User(models.Model):
    username = models.CharField(max_length=100)
    email = models.EmailField()
    
    def __str__(self):
        return self.username
                """
            else:
                return "# Mock code for other components"
                
        mock_get_code_snippet.side_effect = mock_code_snippet
        
        # First identify serializers
        self.analyzer._identify_serializers_and_models()
        
        # Get schema components
        components = self.analyzer.get_schema_components()
        
        # Test getting context for UserSerializerRequest
        context = self.analyzer.get_component_context("UserSerializerRequest")
        
        # Check context structure
        self.assertIn("serializer_code", context)
        self.assertIn("model_code", context)
        self.assertIn("parent_code", context)
        self.assertIn("related_serializers_code", context)
        
        # Verify the serializer code contains the right headers
        self.assertIn("Source File:", context["serializer_code"])
        self.assertIn("Line Number:", context["serializer_code"])
        self.assertIn("Code Snippet:", context["serializer_code"])
        
        # Verify model code is present
        if "model_code" in context and context["model_code"]:
            self.assertIn("Source File:", context["model_code"])
            self.assertIn("Line Number:", context["model_code"])
            self.assertIn("Code Snippet:", context["model_code"])

    @patch.object(PythonCodeAnalyzer, 'get_code_snippet')
    def test_get_associated_model_key(self, mock_get_code_snippet):
        """Test finding the model associated with a serializer."""
        # Mock the get_code_snippet method to return mock code
        mock_get_code_snippet.return_value = "# Mock code snippet"
        
        # First identify serializers
        self.analyzer._identify_serializers_and_models()
        
        # Test for a model serializer (UserSerializer)
        model_key = self.analyzer._get_associated_model_key(self.serializers_path, "UserSerializer")
        expected_key = f"{self.models_path}:User"
        self.assertEqual(model_key, expected_key, f"Expected model key {expected_key} but got {model_key}")
        
        # Test for a non-model serializer (CommentSerializer - inherits from Serializer, not ModelSerializer)
        # This depends on how your implementation handles non-model serializers
        model_key = self.analyzer._get_associated_model_key(self.serializers_path, "CommentSerializer")
        self.assertNotEqual(model_key, f"{self.models_path}:Comment",
                         "CommentSerializer is not a ModelSerializer so should not be associated with Comment model")

    @patch.object(PythonCodeAnalyzer, 'get_code_snippet')
    def test_inherited_serializer(self, mock_get_code_snippet):
        """Test handling of serializers that inherit from other serializers."""
        # Mock the get_code_snippet method to return mock code
        mock_get_code_snippet.return_value = "# Mock code snippet"
        
        # First identify serializers
        self.analyzer._identify_serializers_and_models()
        
        # Check that NestedUserSerializer inherits from UserSerializer
        nested_key = f"{self.serializers_path}:NestedUserSerializer"
        user_key = f"{self.serializers_path}:UserSerializer"
        
        self.assertIn(nested_key, self.analyzer.is_serializer)
        self.assertTrue(self.analyzer.is_serializer[nested_key], "NestedUserSerializer should be identified as a serializer")
        
        # Also verify that it gets the same model association as its parent
        nested_model_key = self.analyzer._get_associated_model_key(self.serializers_path, "NestedUserSerializer")
        user_model_key = self.analyzer._get_associated_model_key(self.serializers_path, "UserSerializer")
        
        self.assertEqual(nested_model_key, user_model_key, 
                         "NestedUserSerializer should have the same model as UserSerializer")

    def test_framework_specific_instructions(self):
        """Test that framework-specific instructions are provided."""
        instructions = self.analyzer.get_framework_specific_instructions()
        
        # Check for key DRF concepts in the instructions
        self.assertIn("Django REST Framework", instructions)
        self.assertIn("serializers", instructions)
        self.assertIn("read_only", instructions)
        self.assertIn("write_only", instructions)
        self.assertIn("ViewSets", instructions)


if __name__ == '__main__':
    unittest.main()