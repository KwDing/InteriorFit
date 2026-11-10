#pragma once

#include "CoreMinimal.h"
#include "Algo/Sort.h"

/** Value-only static hierarchy. Queries allocate nothing; primitive IDs remain authoring order. */
class FInteriorFitSpatialIndex
{
public:
    void Build(const TArray<FBox>& Boxes)
    {
        Nodes.Reset();
        IDs.Reset(Boxes.Num());
        for (int32 Index = 0; Index < Boxes.Num(); ++Index) IDs.Add(Index);
        if (!IDs.IsEmpty()) BuildNode(Boxes, 0, IDs.Num());
    }

    const FBox& GetBounds() const { return Nodes[0].Bounds; }

    template<typename Visitor>
    void FindNearest(const FVector& Point, const FVector& Scale, double& Best, Visitor&& Visit) const
    {
        if (!Nodes.IsEmpty()) VisitNearest(0, Point * Scale, Scale, Best, Visit);
    }

    template<typename Visitor>
    void VisitCrossingEdges(const FVector& Point, Visitor&& Visit) const
    {
        if (!Nodes.IsEmpty()) VisitCrossings(0, Point, Visit);
    }

private:
    struct FNode
    {
        FBox Bounds = FBox(ForceInit);
        int32 Begin = 0;
        int32 Count = 0;
        int32 Left = INDEX_NONE;
        int32 Right = INDEX_NONE;
    };

    int32 BuildNode(const TArray<FBox>& Boxes, int32 Begin, int32 Count)
    {
        const int32 NodeID = Nodes.AddDefaulted();
        FBox Bounds(ForceInit);
        for (int32 Index = Begin; Index < Begin + Count; ++Index) Bounds += Boxes[IDs[Index]];
        Nodes[NodeID].Bounds = Bounds;
        Nodes[NodeID].Begin = Begin;
        Nodes[NodeID].Count = Count;
        if (Count <= 8) return NodeID;
        const FVector Size = Bounds.GetSize();
        const int32 Axis = Size.X >= Size.Y && Size.X >= Size.Z ? 0 : Size.Y >= Size.Z ? 1 : 2;
        Algo::Sort(MakeArrayView(IDs.GetData() + Begin, Count), [&Boxes, Axis](int32 A, int32 B)
        {
            const double CA = Boxes[A].GetCenter()[Axis];
            const double CB = Boxes[B].GetCenter()[Axis];
            return CA == CB ? A < B : CA < CB;
        });
        const int32 Left = BuildNode(Boxes, Begin, Count / 2);
        const int32 Right = BuildNode(Boxes, Begin + Count / 2, Count - Count / 2);
        Nodes[NodeID].Left = Left;
        Nodes[NodeID].Right = Right;
        return NodeID;
    }

    double LowerBound(int32 NodeID, const FVector& Point, const FVector& Scale) const
    {
        const FBox& Box = Nodes[NodeID].Bounds;
        return FBox(Box.Min * Scale, Box.Max * Scale).ComputeSquaredDistanceToPoint(Point);
    }

    template<typename Visitor>
    void VisitNearest(int32 NodeID, const FVector& Point, const FVector& Scale, double& Best, Visitor& Visit) const
    {
        // Conservative numerical margin prevents pruning an equal-distance primitive.
        if (LowerBound(NodeID, Point, Scale) > Best + 1.e-8 * FMath::Max(1.0, Best)) return;
        const FNode& Node = Nodes[NodeID];
        if (Node.Left == INDEX_NONE)
        {
            for (int32 Index = Node.Begin; Index < Node.Begin + Node.Count; ++Index) Visit(IDs[Index], Best);
            return;
        }
        const bool bLeftFirst = LowerBound(Node.Left, Point, Scale) <= LowerBound(Node.Right, Point, Scale);
        VisitNearest(bLeftFirst ? Node.Left : Node.Right, Point, Scale, Best, Visit);
        VisitNearest(bLeftFirst ? Node.Right : Node.Left, Point, Scale, Best, Visit);
    }

    template<typename Visitor>
    void VisitCrossings(int32 NodeID, const FVector& Point, Visitor& Visit) const
    {
        const FNode& Node = Nodes[NodeID];
        if (Point.Y < Node.Bounds.Min.Y || Point.Y > Node.Bounds.Max.Y || Point.X > Node.Bounds.Max.X) return;
        if (Node.Left == INDEX_NONE)
        {
            for (int32 Index = Node.Begin; Index < Node.Begin + Node.Count; ++Index) Visit(IDs[Index]);
            return;
        }
        VisitCrossings(Node.Left, Point, Visit);
        VisitCrossings(Node.Right, Point, Visit);
    }

    TArray<FNode> Nodes;
    TArray<int32> IDs;
};
