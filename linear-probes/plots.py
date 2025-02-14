import plotly.graph_objects as go

def plot_metrics(metrics: dict, title: str = "Training Progress", x_label: str = "Epoch", y_label: str = "Metric", y_range: tuple = (0, 1)):
    """
    Plots multiple line graphs on the same figure.
    
    Args:
        metrics (dict): Dictionary where keys are labels and values are lists of y-values.
        title (str): Title of the plot.
        x_label (str): Label for x-axis.
        y_label (str): Label for y-axis.
        y_range (tuple): y-axis range (default: (0,1)).
    """
    fig = go.Figure()
    
    for label, y_values in metrics.items():
        fig.add_trace(go.Scatter(
            x=list(range(len(y_values))),
            y=y_values,
            name=label,
            line=dict(width=2)
        ))

    fig.update_layout(
        title=title,
        plot_bgcolor='white',
        paper_bgcolor='white',
        font=dict(family='Computer Modern', size=16),
        xaxis=dict(title=x_label, gridcolor='lightgray', showgrid=True, zeroline=False),
        yaxis=dict(title=y_label, gridcolor='lightgray', showgrid=True, zeroline=False, range=y_range),
        legend=dict(x=0.62, y=0.22, bgcolor='rgba(255, 255, 255, 0.8)'),
        margin=dict(l=60, r=20, t=20, b=60),
        width=500, height=400
    )

    return fig