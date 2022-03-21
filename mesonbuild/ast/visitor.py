# Copyright 2019 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This class contains the basic functionality needed to run any interpreter
# or an interpreter-based tool

from .. import mparser

class AstVisitor:
    def __init__(self)  :
        pass

    def visit_default_func(self, node )  :
        pass

    def visit_BooleanNode(self, node )  :
        self.visit_default_func(node)

    def visit_IdNode(self, node )  :
        self.visit_default_func(node)

    def visit_NumberNode(self, node )  :
        self.visit_default_func(node)

    def visit_StringNode(self, node )  :
        self.visit_default_func(node)

    def visit_FormatStringNode(self, node )  :
        self.visit_default_func(node)

    def visit_ContinueNode(self, node )  :
        self.visit_default_func(node)

    def visit_BreakNode(self, node )  :
        self.visit_default_func(node)

    def visit_ArrayNode(self, node )  :
        self.visit_default_func(node)
        node.args.accept(self)

    def visit_DictNode(self, node )  :
        self.visit_default_func(node)
        node.args.accept(self)

    def visit_EmptyNode(self, node )  :
        self.visit_default_func(node)

    def visit_OrNode(self, node )  :
        self.visit_default_func(node)
        node.left.accept(self)
        node.right.accept(self)

    def visit_AndNode(self, node )  :
        self.visit_default_func(node)
        node.left.accept(self)
        node.right.accept(self)

    def visit_ComparisonNode(self, node )  :
        self.visit_default_func(node)
        node.left.accept(self)
        node.right.accept(self)

    def visit_ArithmeticNode(self, node )  :
        self.visit_default_func(node)
        node.left.accept(self)
        node.right.accept(self)

    def visit_NotNode(self, node )  :
        self.visit_default_func(node)
        node.value.accept(self)

    def visit_CodeBlockNode(self, node )  :
        self.visit_default_func(node)
        for i in node.lines:
            i.accept(self)

    def visit_IndexNode(self, node )  :
        self.visit_default_func(node)
        node.iobject.accept(self)
        node.index.accept(self)

    def visit_MethodNode(self, node )  :
        self.visit_default_func(node)
        node.source_object.accept(self)
        node.args.accept(self)

    def visit_FunctionNode(self, node )  :
        self.visit_default_func(node)
        node.args.accept(self)

    def visit_AssignmentNode(self, node )  :
        self.visit_default_func(node)
        node.value.accept(self)

    def visit_PlusAssignmentNode(self, node )  :
        self.visit_default_func(node)
        node.value.accept(self)

    def visit_ForeachClauseNode(self, node )  :
        self.visit_default_func(node)
        node.items.accept(self)
        node.block.accept(self)

    def visit_IfClauseNode(self, node )  :
        self.visit_default_func(node)
        for i in node.ifs:
            i.accept(self)
        node.elseblock.accept(self)

    def visit_UMinusNode(self, node )  :
        self.visit_default_func(node)
        node.value.accept(self)

    def visit_IfNode(self, node )  :
        self.visit_default_func(node)
        node.condition.accept(self)
        node.block.accept(self)

    def visit_TernaryNode(self, node )  :
        self.visit_default_func(node)
        node.condition.accept(self)
        node.trueblock.accept(self)
        node.falseblock.accept(self)

    def visit_ArgumentNode(self, node )  :
        self.visit_default_func(node)
        for i in node.arguments:
            i.accept(self)
        for key, val in node.kwargs.items():
            key.accept(self)
            val.accept(self)
