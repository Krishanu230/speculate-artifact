package com.analyzer.EndPointRecog;

import org.json.simple.JSONArray;
import org.json.simple.JSONObject;

import soot.RefType;
import soot.SootClass;
import soot.SootField;
import soot.tagkit.AnnotationTag;
import soot.tagkit.SignatureTag;
import soot.tagkit.VisibilityAnnotationTag;

import java.util.*;



public class ClassIdentifersInfo {
    public ArrayList<EndPointMethodInfo> functions;
    public String className; 
    public ArrayList<FieldInfo> classFieldsFromInitialPass;
    public ArrayList<EndPointParamInfo> fieldPathParams;
    public ArrayList<String> classPath; // Class-level @Path annotations
    public ArrayList<String> parentClasses; // FQNs of parents
    public ArrayList<AnnotationInfo> annotations; // Class-level annotations
    public transient SootClass sootClass; // Store SootClass for richer field info during toJSON
    public boolean isInterface;
    public boolean isAbstract;
    public boolean isEnum;
     public String classSignature;

    public ClassIdentifersInfo(
            ArrayList<EndPointMethodInfo> functions,
            SootClass sc, 
            ArrayList<FieldInfo> initialFields,
            ArrayList<EndPointParamInfo> fieldPathParams,
            ArrayList<String> parentClassesFqns,
            String classSignature, 
            ArrayList<AnnotationInfo> classAnnotations,
            ArrayList<String> classLevelPaths) {
        this.functions = (functions != null) ? functions : new ArrayList<>();
        this.sootClass = sc;
        this.className = sc.getName();
        this.classFieldsFromInitialPass = (initialFields != null) ? initialFields : new ArrayList<>();
        this.fieldPathParams = (fieldPathParams != null) ? fieldPathParams : new ArrayList<>();
        this.parentClasses = (parentClassesFqns != null) ? parentClassesFqns : new ArrayList<>();
        this.annotations = (classAnnotations != null) ? classAnnotations : new ArrayList<>();
        this.classPath = (classLevelPaths != null) ? classLevelPaths : new ArrayList<>();
        this.isInterface = sc.isInterface();
        this.isAbstract = sc.isAbstract();
        this.isEnum = sc.isEnum(); 
        this.classSignature = classSignature;
    }

    public JSONObject toJSON() {
        JSONObject obj = new JSONObject();
        obj.put("className", this.className);

        JSONArray functionsArray = new JSONArray();
        if (this.functions != null) {
            for (EndPointMethodInfo function : this.functions) {
                if (function != null && function.methodIdentifiersInfo != null) {
                    functionsArray.add(function.methodIdentifiersInfo.toJSON());
                }
                else{
                    System.out.println("Warning: function or methodIdentifiersInfo is null for class " + this.className);
                }
            }
        }
        obj.put("functions", functionsArray);

        JSONArray fieldPathParamsArray = new JSONArray();
        if (this.fieldPathParams != null) {
            for (EndPointParamInfo fieldPathParam : this.fieldPathParams) {
                if (fieldPathParam != null) { // Null check
                    fieldPathParamsArray.add(fieldPathParam.toJSON());
                }
            }
        }
        obj.put("fieldPathParams", fieldPathParamsArray);

        JSONArray fieldsJsonArray = new JSONArray();
        if (this.sootClass != null) {
            for (SootField field : this.sootClass.getFields()) {
                JSONObject fieldJson = new JSONObject();
                fieldJson.put("name", field.getName());

                String typeString = field.getType().toString(); // Default
                SignatureTag sigTag = (SignatureTag) field.getTag("SignatureTag");
                if (sigTag != null) {
                    String parsedGeneric = PreprocessFramework.parseSootGenericSignature(sigTag.getSignature());
                    if (parsedGeneric != null) {
                        typeString = parsedGeneric;
                    } else { // If parseSootGenericSignature returns null (e.g. for "I", "Z")
                        // Use sootDescriptorToJavaFQN as a fallback if it was a descriptor like Ljava/lang/String;
                        String fqnAttempt = PreprocessFramework.sootDescriptorToJavaFQN(sigTag.getSignature());
                        if (fqnAttempt != null && !fqnAttempt.equals(sigTag.getSignature())) { // check if conversion happened
                            typeString = fqnAttempt;
                        } else {
                            // If still no good, the original field.getType().toString() might be best for primitives
                            typeString = field.getType().toString();
                        }
                    }
                } else if (field.getType() instanceof RefType) { // Handle non-generic RefTypes better
                    typeString = ((RefType) field.getType()).getClassName();
                }
                fieldJson.put("type", typeString);

                JSONArray fieldAnnotationsArray = new JSONArray();
                VisibilityAnnotationTag vat = (VisibilityAnnotationTag) field.getTag("VisibilityAnnotationTag");
                if (vat != null) {
                    for (AnnotationTag at : vat.getAnnotations()) {
                        if (at != null) { // Null check
                            fieldAnnotationsArray.add(PreprocessFramework.parseAnnotationTag(at).toJSON());
                        }
                    }
                }
                fieldJson.put("annotations", fieldAnnotationsArray);
                fieldsJsonArray.add(fieldJson);
            }
        }
        obj.put("fields", fieldsJsonArray);

        JSONArray classAnnotationsArray = new JSONArray();
        if (this.annotations != null) {
            for (AnnotationInfo annotation : this.annotations) {
                if (annotation != null) { // Null check
                     classAnnotationsArray.add(annotation.toJSON());
                }
            }
        }
        obj.put("annotations", classAnnotationsArray);

        JSONArray classPathArray = new JSONArray();
        if (this.classPath != null) {
            for (String path : this.classPath) {
                if (path != null) { // Null check
                    classPathArray.add(path);
                }
            }
        }
        obj.put("classPath", classPathArray);

        JSONArray parentClassesArray = new JSONArray();
        if (this.parentClasses != null) {
            for (String parentClass : this.parentClasses) {
                 if (parentClass != null) { // Null check
                    parentClassesArray.add(parentClass);
                 }
            }
        }
        obj.put("parentClasses", parentClassesArray);

        obj.put("isInterface", this.isInterface);
        obj.put("isAbstract", this.isAbstract);
        obj.put("isEnum", this.isEnum); 
        if (this.classSignature != null && !this.classSignature.isEmpty()) {
            obj.put("classSignature", this.classSignature);
        }
        return obj;
    }
}