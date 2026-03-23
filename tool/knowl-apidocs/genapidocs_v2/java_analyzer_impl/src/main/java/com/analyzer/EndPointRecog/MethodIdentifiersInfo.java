package com.analyzer.EndPointRecog;

import java.util.*;

import org.json.simple.JSONObject;
import org.json.simple.JSONArray;
import soot.Type; 


class MethodIdentifier{
    String simpleName ;
    String declaringClass  ;
    List<String> arguments; 

    MethodIdentifier(String simpleName, String declaringClass, List<String> arguments) {
        this.simpleName = simpleName;
        this.declaringClass = declaringClass;
        this.arguments = arguments; // NEW: Assign arguments
    }

    public JSONObject toJSON() {
        JSONObject obj = new JSONObject();
        obj.put("simpleName", this.simpleName);
        obj.put("declaringClass", this.declaringClass);
        JSONArray argsArray = new JSONArray();
        if (this.arguments != null) {
            argsArray.addAll(this.arguments);
        }
        obj.put("arguments", argsArray);
        
        return obj;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        MethodIdentifier that = (MethodIdentifier) o;
        // UPDATED: Include arguments in equality check
        return simpleName.equals(that.simpleName) &&
                declaringClass.equals(that.declaringClass) &&
                Objects.equals(arguments, that.arguments);
    }

    @Override
    public int hashCode() {
        return Objects.hash(simpleName, declaringClass, arguments);
    }

}

class VariableIdentifier{
    String name;
    String type;
    VariableIdentifier(String name, String type) {
        this.name = name;
        this.type = type;
    }
    public JSONObject toJSON() {
        JSONObject obj = new JSONObject();
        obj.put("name", this.name);
        obj.put("type", this.type);
        return obj;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;

        VariableIdentifier that = (VariableIdentifier) o;
        return name.equals(that.name) &&
                type.equals(that.type);
    }

    @Override
    public int hashCode() {
        return (name + type).hashCode();
    }

}

public class MethodIdentifiersInfo{

    public Set<String> classNames = new HashSet<>();
    public Set<MethodIdentifier> functionNames = new HashSet<>();
    public Set<VariableIdentifier> variableNames = new HashSet<>();
    public String methodName ;
    public String className ;
    public ArrayList<AnnotationInfo> annotations; // For method-level annotations
    public String returnTypeString;             // For method return type
    public ArrayList<ParameterInfoForMethod> parameters; // For detailed method parameters
    public String signature;
//    public int startLine ;
//    public int Endline ;

    // define the constructor
    public MethodIdentifiersInfo(Set<String> classNames, Set<MethodIdentifier> functionNames,
                                 Set<VariableIdentifier> variableNames, String methodName, String className,
                                 ArrayList<AnnotationInfo> methodAnnotations, String returnType,
                                 ArrayList<ParameterInfoForMethod> methodParameters,String signature) {
        this.classNames = classNames;
        this.functionNames = functionNames;
        this.variableNames = variableNames;
        this.methodName = methodName;
        this.className = className;
        this.annotations = (methodAnnotations != null) ? methodAnnotations : new ArrayList<>();
        this.returnTypeString = returnType;
        this.parameters = (methodParameters != null) ? methodParameters : new ArrayList<>();
        this.signature = signature;
    }


    public JSONObject toJSON() {
        JSONObject obj = new JSONObject();
        // ... (existing serializations for classNames, functionNames, variableNames, methodName, className)
        obj.put("methodName", methodName);
        obj.put("className", className);

        JSONArray classes = new JSONArray();
        for (String cn : classNames) { classes.add(cn); }
        obj.put("classNames", classes);

        JSONArray functions = new JSONArray();
        for (MethodIdentifier mi : functionNames) { functions.add(mi.toJSON()); }
        obj.put("functionNames", functions);

        JSONArray variables = new JSONArray();
        for (VariableIdentifier vi : variableNames) { variables.add(vi.toJSON()); }
        obj.put("variableNames", variables);


        // SERIALIZE NEW FIELDS:
        JSONArray methodAnnotationsArray = new JSONArray();
        for (AnnotationInfo ai : this.annotations) {
            methodAnnotationsArray.add(ai.toJSON());
        }
        obj.put("annotations", methodAnnotationsArray); // Key named "annotations"

        obj.put("returnType", this.returnTypeString); // Key named "returnType"

        JSONArray parametersArray = new JSONArray();
        for (ParameterInfoForMethod pi : this.parameters) {
            parametersArray.add(pi.toJSON());
        }
        obj.put("parameters", parametersArray); // Key named "parameters"
        obj.put("signature", signature);
        return obj;
    }
}

class ParameterInfoForMethod {
    public String name;
    public String typeString; // FQN with generics
    public ArrayList<AnnotationInfo> annotations;

    public ParameterInfoForMethod(String name, String typeString, ArrayList<AnnotationInfo> annotations) {
        this.name = name;
        this.typeString = typeString;
        this.annotations = (annotations != null) ? annotations : new ArrayList<>();
    }

    public JSONObject toJSON() {
        JSONObject obj = new JSONObject();
        obj.put("name", this.name);
        obj.put("type", this.typeString);
        JSONArray anns = new JSONArray();
        for (AnnotationInfo ai : this.annotations) {
            anns.add(ai.toJSON());
        }
        obj.put("annotations", anns);
        return obj;
    }
}
