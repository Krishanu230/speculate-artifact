package com.analyzer.EndPointRecog;

import soot.tagkit.AnnotationTag;
import soot.tagkit.Host; // For getting tags from Units
import soot.tagkit.LineNumberTag;
import soot.tagkit.SignatureTag;
import soot.tagkit.Tag; // This import is correct IF it's used on a Host
import soot.tagkit.VisibilityAnnotationTag;
import soot.tagkit.VisibilityParameterAnnotationTag;

import soot.*;
import soot.jimple.*; // For Stmt, IdentityStmt, ParameterRef etc.

import java.util.*;



public class GetIdentifiersInfo {
//
//    public static ArrayList<MethodIdentifiersInfo> getIdentifiers(Scene v){
//        Chain<SootClass> appClasses=v.getApplicationClasses();
//        Chain<SootClass> libClasses=v.getLibraryClasses();
//        Chain<SootClass> phantomClasses=v.getPhantomClasses();
//
//        // get framework
////        FrameworkData.FrameworkName framework= decideFramework(libClasses, phantomClasses);
////
////        if(framework== FrameworkData.FrameworkName.Unknown){
////            throw new RuntimeException("Unknown Framework");
////        }
////
////
////        FrameworkData data=FrameworkData.Data.get(framework);
//
//
//
//        // map for class to list of endpoint methods
//        HashMap<SootClass, ArrayList<MethodIdentifiersInfo>> resrcClassToMethods=new HashMap<>();
//
//        ArrayList<MethodIdentifiersInfo> rtv=new ArrayList<>();
//
//        // sort application classes
//        ArrayList<Pair<SootClass, String>> sortedAppClasses=new ArrayList<>();
//        for(SootClass c: appClasses){
//            sortedAppClasses.add(Pair.of(c, c.getName()));
//        }
//        sortedAppClasses.sort((b,a)->a.getRight().compareTo(b.getRight()));
//
//        for(Pair<SootClass, String> p: sortedAppClasses){
//            // ????
//            SootClass c=p.getLeft();
//
////            VisibilityAnnotationTag cTags= (VisibilityAnnotationTag) c.getTag("VisibilityAnnotationTag");
////
////            ArrayList<String> classPath=new ArrayList<>();
////            ArrayList<EndPointParamInfo> fieldPathParams=new ArrayList<>();
////
////            if(cTags != null){
////                ArrayList<AnnotationTag> classAnnos = cTags.getAnnotations();
////                for(AnnotationTag t: classAnnos){
////                    ClassMethodAnnotation CMAnno = data.classAnnotations.get(t.getType());
////
////                    if(CMAnno != null){
////                        classPath.addAll(CMAnno.getPathFrom(t));
////                    }
////                }
////            }
////
////            if(!data.fieldAnnotations.isEmpty()){
////                for(SootField f: c.getFields()){
////                    VisibilityAnnotationTag fieldTag=(VisibilityAnnotationTag) f.getTag("VisibilityAnnotationTag");
////
////                    if(fieldTag==null){
////                        continue;
////                    }
////
////                    ArrayList<VisibilityAnnotationTag> fieldAnnos=new ArrayList<>(List.of(fieldTag));
////                    List<Type> fieldType=List.of(f.getType());
////
////                    ArrayList<EndPointParamInfo> fieldInfo=getAnnotatedParam(fieldAnnos, data.fieldAnnotations, fieldType);
////
////                    if(!fieldInfo.isEmpty()){
////                        fieldPathParams.add(fieldInfo.get(0));
////
////                        logger.debug(String.format("Found annotated field %s in %s", f.getName(), c.getName()));
////                    }
////                }
////            }
//
//            for(SootMethod m:c.getMethods()){
//
////                VisibilityAnnotationTag tags = (VisibilityAnnotationTag) m.getTag("VisibilityAnnotationTag");
////                if(tags==null){
////
////                    continue;
////                }
////
////                ArrayList<String> requestMethod=new ArrayList<>();
////                ArrayList<String> methodPath=new ArrayList<>();
////                int responseStatus=200;
////
////                boolean hasMethodAnnotationsNoSkip=false;
////
////                boolean hasPathExplosion=false;
////
////                for(AnnotationTag mTag: tags.getAnnotations()){
////                    String annoType = mTag.getType();
////
////                    if(
////                        // annoType.equals("Lorg/respector/SkipEndPointForProfile;")||
////                            annoType.equals("Lorg/respector/SkipEndPointForPathExplosion;")
////                    ){
////                        hasPathExplosion=true;
////                        continue;
////                    }
////
////                    ClassMethodAnnotation CMAnno = data.methodAnnotations.get(annoType);
////
////                    if(CMAnno != null){
////                        hasMethodAnnotationsNoSkip=true;
////
////                        methodPath.addAll(CMAnno.getPathFrom(mTag));
////
////                        requestMethod.addAll(CMAnno.getRequestMethodFrom(mTag));
////                    }
////
////                    ClassMethodAnnotation CRAnno = data.responseStatusAnnotations.get(annoType);
////                    if(CRAnno!=null){
////                        Integer rtStatus=CRAnno.getResponseStatus(mTag, data.nameToResponse);
////                        if(rtStatus!=null){
////                            responseStatus=rtStatus;
////                        }
////                    }
////                }
////
////                if(!hasMethodAnnotationsNoSkip){
////                    continue;
////                }
////
////                ///TODO: fix this
////                if(requestMethod.isEmpty()){
////                    if(framework== FrameworkData.FrameworkName.Spring){
////                        requestMethod.addAll(List.of("get", "post", "head", "options", "put", "patch", "delete", "trace"));
////                    }
////                }
////
////                VisibilityParameterAnnotationTag paramTags=(VisibilityParameterAnnotationTag) m.getTag("VisibilityParameterAnnotationTag");
////                ArrayList<EndPointParamInfo> paramInfo;
////                if(paramTags==null){
////                    paramInfo=new ArrayList<>();
////                }
////                else{
////
////                    ArrayList<VisibilityAnnotationTag> paramAnnos=paramTags.getVisibilityAnnotations();
////
////                    List<Type> paramTypes= m.getParameterTypes();
////
////                    paramInfo=getAnnotatedParam(paramAnnos, data.paramAnnotations, paramTypes);
////
////                    // DONE: no argument end point?
////                    // keep them
////                    // if(paramInfo.isEmpty()){
////                    // continue;
////                    // }
////                }
//                Map<String, Set<String>> identifiers = extractIdentifiersFromMethod(m);
//
//                String methodName = m.getName();
//                String className = c.getName();
//                MethodIdentifiersInfo toAdd = new MethodIdentifiersInfo(identifiers.get("classes"),
//                        identifiers.get("functions"),
//                        identifiers.get("variables"),
//                        methodName,
//                        className);
//                rtv.add(toAdd);
//                // update resrcClassToMethods
//                if(resrcClassToMethods.containsKey(c)){
//                    resrcClassToMethods.get(c).add(toAdd);
//                }
//                else{
//                    ArrayList<MethodIdentifiersInfo> newList=new ArrayList<>();
//                    newList.add(toAdd);
//                    resrcClassToMethods.put(c, newList);
//                }
//            }
//
//        }
//        return rtv ;
//    }

    public static MethodIdentifiersInfo extractIdentifiersFromMethod(SootMethod method, SootClass c) {
        Set<String> classNames = new HashSet<>();
        Set<MethodIdentifier> functionNames = new HashSet<>();
        Set<VariableIdentifier> variableNames = new HashSet<>();

        String methodName = method.getName();
        String className = c.getName();

        // --- 1. Extract Method-Level Annotations ---
        ArrayList<AnnotationInfo> methodAnnotations = new ArrayList<>();
        VisibilityAnnotationTag vat = (VisibilityAnnotationTag) method.getTag("VisibilityAnnotationTag");
        if (vat != null) {
            for (AnnotationTag at : vat.getAnnotations()) {
                methodAnnotations.add(PreprocessFramework.parseAnnotationTag(at));
            }
        }

        // --- 2. Extract Return Type ---
        String returnTypeStr = method.getReturnType().toString(); // Default
        SignatureTag sigTag = (SignatureTag) method.getTag("SignatureTag"); // Method's signature tag
        if (sigTag != null) {
            String fullMethodSignature = sigTag.getSignature();
            int closingParenIndex = fullMethodSignature.indexOf(')');
            if (closingParenIndex != -1 && closingParenIndex + 1 < fullMethodSignature.length()) {
                String returnDescriptor = fullMethodSignature.substring(closingParenIndex + 1);
                String parsedReturn = PreprocessFramework.parseSootGenericSignature(returnDescriptor);
                if (parsedReturn != null) {
                    returnTypeStr = parsedReturn;
                } else {
                    String fqnAttempt = PreprocessFramework.sootDescriptorToJavaFQN(returnDescriptor);
                    returnTypeStr = (fqnAttempt != null) ? fqnAttempt : method.getReturnType().toString();
                }
            }
        } else if (method.getReturnType() instanceof RefType) {
            returnTypeStr = ((RefType) method.getReturnType()).getClassName();
        } else if (method.getReturnType() instanceof ArrayType) {
            // Handle array return types more explicitly if parseSootGenericSignature doesn't cover it fully
            Type base = ((ArrayType)method.getReturnType()).baseType;
            String baseStr = (base instanceof RefType) ? ((RefType)base).getClassName() : base.toString();
            returnTypeStr = baseStr + "[]".repeat(((ArrayType)method.getReturnType()).numDimensions);
        }


        // --- 3. Extract Detailed Parameter Information ---
        ArrayList<ParameterInfoForMethod> methodParametersInfoList = new ArrayList<>();
        List<Type> parameterTypes = method.getParameterTypes();
        VisibilityParameterAnnotationTag vpat = (VisibilityParameterAnnotationTag) method.getTag("VisibilityParameterAnnotationTag");
        List<VisibilityAnnotationTag> paramAnnotationTagsList = (vpat != null) ? vpat.getVisibilityAnnotations() : Collections.nCopies(parameterTypes.size(), null);

        for (int i = 0; i < parameterTypes.size(); i++) {
            Type paramType = parameterTypes.get(i);
            String paramTypeStr = paramType.toString(); // Default

            if (sigTag != null) { // Try to parse from full method signature for generics
                String fullMethodSig = sigTag.getSignature();
                // This requires a robust parser for "(LType1<...>;LType2;)..." to get i-th param's generic sig
                // For now, we'll use a simpler approach that might miss top-level generics on params
                String parsedParamType = PreprocessFramework.parseSootGenericSignature(paramType.toString()); // Attempt on simple toString
                if (parsedParamType != null) paramTypeStr = parsedParamType;
                else if (paramType instanceof RefType) paramTypeStr = ((RefType)paramType).getClassName();
                else if (paramType instanceof ArrayType) {
                    Type base = ((ArrayType)paramType).baseType;
                    String baseStr = (base instanceof RefType) ? ((RefType)base).getClassName() : base.toString();
                    paramTypeStr = baseStr + "[]".repeat(((ArrayType)paramType).numDimensions);
                }


            } else if (paramType instanceof RefType) {
                paramTypeStr = ((RefType)paramType).getClassName();
            } else if (paramType instanceof ArrayType) {
                 Type base = ((ArrayType)paramType).baseType;
                 String baseStr = (base instanceof RefType) ? ((RefType)base).getClassName() : base.toString();
                 paramTypeStr = baseStr + "[]".repeat(((ArrayType)paramType).numDimensions);
            }


            ArrayList<AnnotationInfo> paramAnns = new ArrayList<>();
            if (i < paramAnnotationTagsList.size() && paramAnnotationTagsList.get(i) != null) {
                for (AnnotationTag at : paramAnnotationTagsList.get(i).getAnnotations()) {
                    paramAnns.add(PreprocessFramework.parseAnnotationTag(at));
                }
            }
            // Placeholder for parameter name, will be updated if LocalNameTag is found on IdentityStmt
            methodParametersInfoList.add(new ParameterInfoForMethod("param" + i, paramTypeStr, paramAnns));
        }

        // --- Body Analysis ---
        if (!method.isConcrete() || !method.hasActiveBody()) {
            // System.out.println("Method " + method.getSignature() + " has no active body or is not concrete.");
            return new MethodIdentifiersInfo(classNames, functionNames, variableNames, methodName, className,
                                             methodAnnotations, returnTypeStr, methodParametersInfoList, method.getSignature());
        }
        Body body = method.getActiveBody();

        // Refine parameter names using IdentityStmts
        for (Unit unit : body.getUnits()) {
            if (unit instanceof IdentityStmt) {
                IdentityStmt idStmt = (IdentityStmt) unit;
                if (idStmt.getRightOp() instanceof ParameterRef) {
                    ParameterRef pRef = (ParameterRef) idStmt.getRightOp();
                    int paramIndex = pRef.getIndex();
                    if (idStmt.getLeftOp() instanceof Local) {
                        Local paramLocal = (Local) idStmt.getLeftOp();
                        String actualParamName = paramLocal.getName(); // Use Local.getName() directly

                        // The LocalNameTag logic is removed as it's causing compilation errors
                        // and Local.getName() might provide the original name if available.

                        if (paramIndex < methodParametersInfoList.size()) {
                            methodParametersInfoList.get(paramIndex).name = actualParamName;
                        }
                    }
                }
            }
        }

        processMethodSignature(method, classNames);

        for (Local local : body.getLocals()) {
            boolean isParameter = false;
            // Check if this local corresponds to a parameter already named
            for(ParameterInfoForMethod pInfo : methodParametersInfoList) {
                // This check is heuristic: Soot's local name for a parameter might match
                // the name we assigned in the loop above.
                if(pInfo.name.equals(local.getName())) {
                     // A more robust check would be if 'local' IS one of the ParameterRef locals.
                     // This requires iterating IdentityStmts again or storing ParameterRef locals.
                     // For now, simple name check to avoid re-adding.
                     for (Unit unit : body.getUnits()) {
                        if (unit instanceof IdentityStmt) {
                            IdentityStmt idStmt = (IdentityStmt) unit;
                            if (idStmt.getLeftOp().equivTo(local) && idStmt.getRightOp() instanceof ParameterRef) {
                                isParameter = true;
                                break;
                            }
                        }
                     }
                     if(isParameter) break;
                }
            }
            if (isParameter) continue;

            String localName = local.getName(); // Use Local.getName()
            String localType = processType(local.getType(), classNames);
            variableNames.add(new VariableIdentifier(localName, localType));
        }

        for (Unit unit : body.getUnits()) {
            if (unit instanceof Stmt) {
                processStmt((Stmt) unit, classNames, functionNames, variableNames);
            }
        }

        return new MethodIdentifiersInfo(classNames, functionNames, variableNames, methodName, className,
                                         methodAnnotations, returnTypeStr, methodParametersInfoList, method.getSignature());
    }

    private static void processMethodSignature(SootMethod method, Set<String> classNames) {
        processType(method.getReturnType(), classNames);
        for (Type paramType : method.getParameterTypes()) {
            processType(paramType, classNames);
        }
    }


    private static String processType(Type type, Set<String> classNames) {
        if (type instanceof RefType) {
            String className = ((RefType) type).getClassName();
            if (!isCommonType(className)) {
                classNames.add(className);
            }
            return className;
        } else if (type instanceof ArrayType) {
            String baseTypeStr = processType(((ArrayType) type).getElementType(), classNames);
            return baseTypeStr + "[]".repeat(((ArrayType) type).numDimensions);
        }
        return type.toString();
    }

    private static boolean isCommonType(String className) {
         return className.startsWith("java.lang.") ||
                className.startsWith("java.util.") ||
                className.equals("int") ||
                className.equals("boolean") ||
                className.equals("double") ||
                className.equals("float") ||
                className.equals("byte") ||
                className.equals("char") ||
                className.equals("short") ||
                className.equals("long") ||
                className.equals("void");
    }

    private static void processStmt(Stmt stmt, Set<String> classNames,
                                    Set<MethodIdentifier> functionNames, Set<VariableIdentifier> variableNames) {
        // Process method invocations - applies to multiple statement types
        if (stmt.containsInvokeExpr()) {
            processInvokeExpr(stmt.getInvokeExpr(), classNames, functionNames, variableNames);
        }

        // Handle different statement types
        if (stmt.containsInvokeExpr()) {
            processInvokeExpr(stmt.getInvokeExpr(), classNames, functionNames, variableNames);
        }

        // Handle different statement types
        if (stmt instanceof AssignStmt) {
            // AssignStmt: x = y
            AssignStmt assignStmt = (AssignStmt) stmt;
            processValue(assignStmt.getLeftOp(), classNames, functionNames, variableNames);
            processValue(assignStmt.getRightOp(), classNames, functionNames, variableNames);
        }
        else if (stmt instanceof IdentityStmt) {
            // IdentityStmt: x := @parameter0, x := @this, x := @caughtexception
            IdentityStmt identityStmt = (IdentityStmt) stmt;
            processValue(identityStmt.getLeftOp(), classNames, functionNames, variableNames);
            processValue(identityStmt.getRightOp(), classNames, functionNames, variableNames);
        }
        else if (stmt instanceof InvokeStmt) {
            InvokeStmt invokeStmt = (InvokeStmt) stmt;
            processInvokeExpr(invokeStmt.getInvokeExpr(), classNames, functionNames, variableNames);
        }
        else if (stmt instanceof ReturnStmt) {
            ReturnStmt returnStmt = (ReturnStmt) stmt;
            processValue(returnStmt.getOp(), classNames, functionNames, variableNames);
        }

        else if (stmt instanceof ReturnVoidStmt) {
            // ReturnVoidStmt: return (no value to process)
            // No values to extract
        }
        else if (stmt instanceof ThrowStmt) {
            // ThrowStmt: throw e
            ThrowStmt throwStmt = (ThrowStmt) stmt;
            processValue(throwStmt.getOp(), classNames, functionNames, variableNames);
        }
        else if (stmt instanceof IfStmt) {
            // IfStmt: if (x == y) goto label
            IfStmt ifStmt = (IfStmt) stmt;
            processValue(ifStmt.getCondition(), classNames, functionNames, variableNames);
        }
        else if (stmt instanceof GotoStmt) {
            // GotoStmt: goto label
            // No values to extract
        }
        else if (stmt instanceof TableSwitchStmt) {
            // TableSwitchStmt: switch with consecutive case values
            TableSwitchStmt tableSwitchStmt = (TableSwitchStmt) stmt;
            processValue(tableSwitchStmt.getKey(), classNames, functionNames, variableNames);
        }
        else if (stmt instanceof LookupSwitchStmt) {
            // LookupSwitchStmt: switch with non-consecutive case values
            LookupSwitchStmt lookupSwitchStmt = (LookupSwitchStmt) stmt;
            processValue(lookupSwitchStmt.getKey(), classNames, functionNames, variableNames);

            // Process lookup values if they contain any complex expressions
            for (Value lookupValue : lookupSwitchStmt.getLookupValues()) {
                processValue(lookupValue, classNames, functionNames, variableNames);
            }
        }
        else if (stmt instanceof EnterMonitorStmt) {
            // EnterMonitorStmt: monitorenter x
            EnterMonitorStmt enterMonitorStmt = (EnterMonitorStmt) stmt;
            processValue(enterMonitorStmt.getOp(), classNames, functionNames, variableNames);
        }
        else if (stmt instanceof ExitMonitorStmt) {
            // ExitMonitorStmt: monitorexit x
            ExitMonitorStmt exitMonitorStmt = (ExitMonitorStmt) stmt;
            processValue(exitMonitorStmt.getOp(), classNames, functionNames, variableNames);
        }
        else if (stmt instanceof NopStmt) {
            // NopStmt: no-operation
            // No values to extract
        }
        else if (stmt instanceof BreakpointStmt) {
            // BreakpointStmt: breakpoint
            // No values to extract
        }

        // Use boxes to ensure we catch any values not specifically handled above
        for (ValueBox vb : stmt.getUseAndDefBoxes()) {
            processValue(vb.getValue(), classNames, functionNames, variableNames);
        }
    }
    
    private static void processValue(Value value, Set<String> classNames,
                                     Set<MethodIdentifier> functionNames, Set<VariableIdentifier> variableNames) {
        // Base cases
        if (value instanceof Local) {
        // We don't try to get original name via LocalNameTag here anymore for general locals.
        // We just record the Local as Soot sees it.
        // Parameters names are refined earlier.
    }
        else if (value instanceof Constant) {
        if (value instanceof StringConstant) {
            if (!isCommonType("java.lang.String")) classNames.add("java.lang.String");
        } else if (value instanceof ClassConstant) {
            String className = ((ClassConstant) value).getValue().replace('/', '.');
            if (!isCommonType(className)) classNames.add(className);
        }
    }
    else if (value instanceof InstanceFieldRef) {
        InstanceFieldRef ifr = (InstanceFieldRef) value;
        // String name = ifr.getField().getName(); // Field name
        String declaringClass = ifr.getField().getDeclaringClass().getName() ; // Class FQN
        // variableNames.add(new VariableIdentifier(name, declaringClass + "." + name)); // Or just type?
        if (!isCommonType(declaringClass)) classNames.add(declaringClass);
        processType(ifr.getType(), classNames); // Add field's type
        processValue(ifr.getBase(), classNames, functionNames, variableNames); // Process base object
    }
    else if (value instanceof StaticFieldRef) {
        StaticFieldRef sfr = (StaticFieldRef) value;
        String declaringClass = sfr.getField().getDeclaringClass().getName();
         if (!isCommonType(declaringClass)) classNames.add(declaringClass);
        processType(sfr.getType(), classNames); // Add field's type
    }
    // Recursive cases (InvokeExpr, NewExpr, NewArrayExpr, BinopExpr, UnopExpr, CastExpr, InstanceOfExpr)
    // should remain as they are, ensuring they call processType for any types encountered.
    else if (value instanceof InvokeExpr) {
        processInvokeExpr((InvokeExpr) value, classNames, functionNames, variableNames);
    }
    else if (value instanceof NewExpr) {
        NewExpr newExpr = (NewExpr) value;
        processType(newExpr.getBaseType(), classNames); // This will add the class to classNames
    }
    else if (value instanceof NewArrayExpr) {
        NewArrayExpr newArrayExpr = (NewArrayExpr) value;
        processType(newArrayExpr.getBaseType(), classNames); // Process element type
        processValue(newArrayExpr.getSize(), classNames, functionNames, variableNames); // Process size expression
    }
     else if (value instanceof BinopExpr) {
        BinopExpr binopExpr = (BinopExpr) value;
        processValue(binopExpr.getOp1(), classNames, functionNames, variableNames);
        processValue(binopExpr.getOp2(), classNames, functionNames, variableNames);
    }
    else if (value instanceof UnopExpr) {
        UnopExpr unopExpr = (UnopExpr) value;
        processValue(unopExpr.getOp(), classNames, functionNames, variableNames);
    }
    else if (value instanceof CastExpr) {
        CastExpr castExpr = (CastExpr) value;
        processType(castExpr.getCastType(), classNames);
        processValue(castExpr.getOp(), classNames, functionNames, variableNames);
    }
    else if (value instanceof InstanceOfExpr) {
        InstanceOfExpr instanceOfExpr = (InstanceOfExpr) value;
        processType(instanceOfExpr.getCheckType(), classNames);
        processValue(instanceOfExpr.getOp(), classNames, functionNames, variableNames);
    }

    // Fallback through use boxes
    for (ValueBox vb : value.getUseBoxes()) {
        processValue(vb.getValue(), classNames, functionNames, variableNames);
    }
}

private static void processInvokeExpr(InvokeExpr invokeExpr, Set<String> classNames,
                                      Set<MethodIdentifier> functionNames, Set<VariableIdentifier> variableNames) {
    SootMethod invokedMethod = invokeExpr.getMethod();
    String methodName = invokedMethod.getName();
    String declaringClassFQN = invokedMethod.getDeclaringClass().getName();

    if (!isCommonType(declaringClassFQN)) {
        classNames.add(declaringClassFQN);
    }

    List<String> argNames = new ArrayList<>();
    for (Value arg : invokeExpr.getArgs()) {
        // arg.toString() provides the name of the local variable (e.g., "servletRequest")
        // or the representation of a constant.
        argNames.add(arg.toString());
    }

    // 2. Pass the populated list to the updated MethodIdentifier constructor.
    functionNames.add(new MethodIdentifier(methodName, declaringClassFQN, argNames));

    processType(invokedMethod.getReturnType(), classNames);

    if (invokeExpr instanceof InstanceInvokeExpr) {
        processValue(((InstanceInvokeExpr) invokeExpr).getBase(), classNames, functionNames, variableNames);
    }

    // The recursive call on arguments is still valuable for dependency discovery,
    // so we keep it.
    for (Value arg : invokeExpr.getArgs()) {
        processValue(arg, classNames, functionNames, variableNames);
    }
}





//    private static Pair<Integer, Integer> getMethodLineNumbers(SootMethod method) {
//        if (!method.hasActiveBody()) {
//            try {
//                method.retrieveActiveBody();
//            } catch (Exception e) {
//                return Pair.of(-1,-1);
//            }
//        }
//
//        Body body = method.getActiveBody();
//        int startLine = Integer.MAX_VALUE;
//        int endLine = -1;
//
//        for (Unit unit : body.getUnits()) {
//            LineNumberTag tag = (LineNumberTag) unit.getTag("LineNumberTag");
//            if (tag != null) {
//                int line = tag.getLineNumber();
//                if (line < startLine) startLine = line;
//                if (line > endLine) endLine = line;
//            }
//        }
//
//        if (startLine != Integer.MAX_VALUE && endLine != -1) {
//            return Pair.of(startLine, endLine);
//        } else {
//            return Pair.of(-1,-1); // or Pair.of(-1, -1) to indicate no line info
//        }
//    }




}
