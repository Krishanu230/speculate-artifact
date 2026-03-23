package com.analyzer.EndPointRecog;


import org.json.simple.JSONArray;
import org.json.simple.JSONObject;
import soot.Type;
import soot.RefType;
import soot.ArrayType; 

import java.util.ArrayList;

class AnnotationInfo {
    public String type;
    public ArrayList<AnnotationElementInfo> elements;

    public AnnotationInfo(String type) {
        this.type = type;
        this.elements = new ArrayList<>();
    }

    @SuppressWarnings("unchecked")
    public JSONObject toJSON() {
        JSONObject obj = new JSONObject();
        obj.put("type", this.type);
        JSONArray elementsArray = new JSONArray();
        for (AnnotationElementInfo element : this.elements) {
            elementsArray.add(element.toJSON());
        }
        obj.put("elements", elementsArray);
        return obj;
    }
}

class AnnotationElementInfo {
    public String name;
    public Object value; // Stays as Object to handle String, List, or AnnotationInfo
    public String kind;

    // Constructor for simple string-like values
    public AnnotationElementInfo(String name, String value, String kind) {
        this.name = name;
        this.value = value;
        this.kind = kind;
    }

    // Constructor for array values (can contain Strings or AnnotationInfo objects)
    public AnnotationElementInfo(String name, ArrayList<?> valueList, String kind) {
        this.name = name;
        this.value = valueList;
        this.kind = kind;
    }
    
    // Constructor for a single nested annotation value
    public AnnotationElementInfo(String name, AnnotationInfo nestedAnnotation, String kind) {
        this.name = name;
        this.value = nestedAnnotation;
        this.kind = kind;
    }

    @SuppressWarnings("unchecked")
    public JSONObject toJSON() {
        JSONObject obj = new JSONObject();
        obj.put("name", this.name);

        if (this.value instanceof ArrayList) {
            JSONArray arr = new JSONArray();
            for (Object item : (ArrayList<?>) this.value) {
                if (item instanceof AnnotationInfo) {
                    arr.add(((AnnotationInfo) item).toJSON());
                } else {
                    arr.add(item);
                }
            }
            obj.put("value", arr);
        } else if (this.value instanceof AnnotationInfo) {
            obj.put("value", ((AnnotationInfo) this.value).toJSON());
        } else {
            obj.put("value", this.value);
        }
        obj.put("kind", this.kind);
        return obj;
    }
}

public class FieldInfo {
    public String name;
    public Type type; // soot.Type
    public ArrayList<AnnotationInfo> annotations;

    public FieldInfo(String name, Type type) {
        this.name = name;
        this.type = type;
        this.annotations = new ArrayList<>();
    }

    private String getDetailedTypeString(Type sootType) {
        if (sootType instanceof RefType) {
            return sootType.toString();
        } else if (sootType instanceof ArrayType) {
            ArrayType arrayType = (ArrayType) sootType;
            return getDetailedTypeString(arrayType.getElementType()) + "[]";
        }
        return sootType.toString();
    }

    @SuppressWarnings("unchecked")
    public JSONObject toJSON() {
        JSONObject obj = new JSONObject();
        obj.put("name", this.name);
        obj.put("type", getDetailedTypeString(this.type));
        JSONArray annotationsArray = new JSONArray();
        for (AnnotationInfo annotation : this.annotations) {
            annotationsArray.add(annotation.toJSON());
        }
        obj.put("annotations", annotationsArray);
        return obj;
    }
}